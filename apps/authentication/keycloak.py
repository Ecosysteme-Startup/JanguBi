"""Validation des jetons d'accès Keycloak (OIDC) et provisioning des personnes (EF-AUTH-01, -02, -05).

Seule authentification de l'API : tout jeton Bearer est validé ici (émetteur, signature
JWKS, audience, expiration) ; un jeton invalide donne 401.
"""

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header

logger = logging.getLogger(__name__)

_JWKS_CACHE_KEY = "keycloak:jwks"
_JWKS_REFRESH_LOCK_KEY = "keycloak:jwks:refresh-lock"
_ALGORITHMS = ["RS256"]


class KeycloakTokenError(Exception):
    """Jeton Keycloak invalide. ``code`` sert au message d'erreur et au code WebSocket."""

    def __init__(self, message: str, code: str = "invalid_token") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class KeycloakIdentity:
    sub: str
    email: str
    email_verified: bool
    given_name: str
    family_name: str
    realm_roles: frozenset[str]
    amr: frozenset[str]
    acr: str
    claims: dict[str, Any] = field(repr=False, compare=False, hash=False)
    # Attribut de profil Keycloak facultatif « phone » (claim OIDC ``phone_number``), saisi à l'inscription.
    phone_number: str = field(default="", repr=False)
    # Attribut de profil Keycloak facultatif « birthdate » (claim OIDC ``birthdate``, AAAA-MM-JJ), saisi à l'inscription.
    birthdate: str = field(default="", repr=False)

    @property
    def mfa(self) -> bool:
        return bool(self.amr & set(settings.KEYCLOAK_MFA_AMR_VALUES)) or self.acr in settings.KEYCLOAK_MFA_ACR_VALUES


# --- JWKS -------------------------------------------------------------------------------


def _jwks_fetch() -> dict[str, Any]:
    response = httpx.get(settings.KEYCLOAK_JWKS_URL, timeout=5.0)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or "keys" not in data:
        raise KeycloakTokenError("JWKS Keycloak invalide.", code="jwks_unavailable")
    return data


def jwks_get(*, force_refresh: bool = False) -> dict[str, Any]:
    jwks = None if force_refresh else cache.get(_JWKS_CACHE_KEY)
    if jwks is None:
        try:
            jwks = _jwks_fetch()
        except (httpx.HTTPError, ValueError) as exc:
            logger.error("keycloak.jwks_unavailable", extra={"error": str(exc)})
            raise KeycloakTokenError("Service d'authentification indisponible.", code="jwks_unavailable") from exc
        cache.set(_JWKS_CACHE_KEY, jwks, settings.KEYCLOAK_JWKS_CACHE_SECONDS)
    return jwks


def _signing_key(kid: str) -> Any:
    for attempt in range(2):
        jwks = jwks_get(force_refresh=attempt == 1)
        for key in jwks.get("keys", []):
            if key.get("kid") == kid and key.get("use", "sig") == "sig" and key.get("kty") == "RSA":
                return jwt.PyJWK(key).key
        # kid inconnu : rotation des clés possible → un seul rechargement par minute.
        if attempt == 0 and not cache.add(_JWKS_REFRESH_LOCK_KEY, 1, 60):
            break
    raise KeycloakTokenError("Clé de signature inconnue.", code="unknown_key")


# --- Jetons -------------------------------------------------------------------------------


def is_keycloak_token(token: str) -> bool:
    """Vrai si l'émetteur (non vérifié) est le realm : sert au tri entre Keycloak et SimpleJWT."""
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return False
    return claims.get("iss") == settings.KEYCLOAK_ISSUER


def token_validate(token: str) -> KeycloakIdentity:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise KeycloakTokenError("Jeton illisible.") from exc
    if header.get("alg") not in _ALGORITHMS:
        raise KeycloakTokenError("Algorithme de signature refusé.")
    key = _signing_key(header.get("kid", ""))
    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=_ALGORITHMS,
            audience=settings.KEYCLOAK_AUDIENCE,
            issuer=settings.KEYCLOAK_ISSUER,
            leeway=settings.KEYCLOAK_LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "sub", "iss", "aud", "azp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise KeycloakTokenError("Jeton expiré.", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise KeycloakTokenError(f"Jeton refusé : {exc}.") from exc

    if claims.get("typ", "Bearer") != "Bearer":
        raise KeycloakTokenError("Seul un jeton d'accès est accepté.")
    if claims.get("azp") not in settings.KEYCLOAK_ALLOWED_CLIENTS:
        raise KeycloakTokenError("Client OIDC non autorisé.")
    return KeycloakIdentity(
        sub=str(claims["sub"]),
        email=str(claims.get("email", "")).lower(),
        email_verified=bool(claims.get("email_verified", False)),
        given_name=str(claims.get("given_name", "")),
        family_name=str(claims.get("family_name", "")),
        realm_roles=frozenset(claims.get("realm_access", {}).get("roles", [])),
        amr=frozenset(claims.get("amr", []) or []),
        acr=str(claims.get("acr", "")),
        claims=claims,
        phone_number=str(claims.get("phone_number") or ""),
        birthdate=str(claims.get("birthdate") or ""),
    )


# --- Provisioning (EF-AUTH-02) -----------------------------------------------------------


def _person_by_sub(user_model: Any, sub: str) -> Any:
    return user_model.objects.filter(keycloak_sub=sub).first()


@transaction.atomic
def person_from_identity(identity: KeycloakIdentity) -> Any:
    """Personne liée au ``sub`` ; à défaut, compte existant de même e-mail **vérifié**
    (comptes migrés) ; sinon création d'un fidèle. Idempotent."""
    User = get_user_model()
    person = _person_by_sub(User, identity.sub)
    if person is not None:
        return person
    if identity.email and identity.email_verified:
        person = (
            User.objects.select_for_update().filter(email__iexact=identity.email, keycloak_sub__isnull=True).first()
        )
        if person is not None:
            person.keycloak_sub = identity.sub
            person.save(update_fields=["keycloak_sub", "updated_at"])
            _profile_ensure(person, identity)
            return person
    if not identity.email:
        raise KeycloakTokenError("Le jeton ne contient pas d'adresse e-mail.", code="email_missing")
    if User.objects.filter(email__iexact=identity.email).exists():
        # Première connexion : les requêtes simultanées du front arrivent ensemble et l'une
        # d'elles a pu créer le compte entre-temps. C'est le même ``sub`` : on le renvoie.
        concurrent = _person_by_sub(User, identity.sub)
        if concurrent is not None:
            return concurrent
        # Compte existant mais e-mail non vérifié côté Keycloak (ou déjà lié ailleurs) :
        # jamais de rattachement, sinon prise de compte par simple inscription.
        raise KeycloakTokenError("Un compte existe déjà avec cette adresse.", code="email_conflict")
    try:
        with transaction.atomic():
            person = User.objects.create_user(
                email=identity.email,
                phone_number=None,
                password=None,
                is_active=True,
                is_verified=identity.email_verified,
                keycloak_sub=identity.sub,
            )
    except (IntegrityError, DjangoValidationError) as exc:
        # Course entre deux premières requêtes simultanées (``full_clean`` lève une
        # ValidationError avant la contrainte en base), ou e-mail déjà pris par un compte non
        # vérifié : on relit par sub, sinon on refuse (pas de prise de compte).
        person = _person_by_sub(User, identity.sub)
        if person is None:
            raise KeycloakTokenError("Un compte existe déjà avec cette adresse.", code="email_conflict") from exc
        return person
    _profile_ensure(person, identity)
    return person


def phone_from_claim(raw: str) -> str | None:
    """Numéro saisi à l'inscription (« 77 412 36 58 », « +221 77… ») au format E.164 du
    ``Profile.phone`` ; ``None`` s'il est absent ou invalide (jamais bloquant)."""
    import phonenumbers

    if not raw or not raw.strip():
        return None
    try:
        number = phonenumbers.parse(raw, "SN")
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(number):
        return None
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


BIRTHDATE_MIN = datetime.date(1900, 1, 1)


def birthdate_from_claim(raw: str, *, today: datetime.date | None = None) -> datetime.date | None:
    """Date de naissance saisie à l'inscription (claim OIDC ``birthdate``, AAAA-MM-JJ) ;
    ``None`` si elle est absente, mal formée ou invraisemblable (jamais bloquant)."""
    try:
        value = datetime.date.fromisoformat(raw.strip()) if raw and len(raw.strip()) == 10 else None
    except ValueError:
        return None
    if value is None:
        return None
    if not BIRTHDATE_MIN <= value <= (today or timezone.localdate()):
        return None
    return value


def _profile_ensure(person: Any, identity: KeycloakIdentity) -> None:
    """Profil créé depuis le jeton. Le téléphone et la date de naissance du jeton ne remplissent
    qu'un champ vide : une valeur déjà saisie dans l'application n'est jamais écrasée."""
    from apps.users.models import Profile

    phone = phone_from_claim(identity.phone_number)
    birthdate = birthdate_from_claim(identity.birthdate)
    profile, created = Profile.objects.get_or_create(
        user=person,
        defaults={
            "first_name": identity.given_name[:50],
            "last_name": identity.family_name[:50],
            "phone": phone,
            "date_of_birth": birthdate,
        },
    )
    if created:
        return
    fields = []
    if phone and not profile.phone:
        profile.phone = phone
        fields.append("phone")
    if birthdate and not profile.date_of_birth:
        profile.date_of_birth = birthdate
        fields.append("date_of_birth")
    if fields:
        profile.save(update_fields=[*fields, "updated_at"])


def user_attach_identity(user: Any, identity: KeycloakIdentity) -> Any:
    """Porte les rôles de realm et la MFA sur l'objet utilisateur de la requête."""
    user.keycloak_identity = identity
    return user


def activity_stamp(user: Any, *, mfa: bool) -> None:
    """Dernière activité (et connexion MFA) au jour près ; au plus une écriture par jour."""
    today = timezone.localdate()
    fields = {}
    if user.last_seen_on != today:
        fields["last_seen_on"] = today
    if mfa and user.last_mfa_on != today:
        fields["last_mfa_on"] = today
    if not fields:
        return
    try:
        with transaction.atomic():  # point de sauvegarde : un échec n'empoisonne pas la requête
            get_user_model().objects.filter(pk=user.pk).update(**fields)
    except DatabaseError:
        logger.warning("keycloak.activity_stamp_failed", exc_info=True)  # tampon au mieux, jamais bloquant
        return
    for name, value in fields.items():
        setattr(user, name, value)


def authenticate_token(token: str, identity: KeycloakIdentity | None = None) -> tuple[Any, KeycloakIdentity]:
    identity = identity or token_validate(token)
    user = person_from_identity(identity)
    if not user.is_active:
        raise KeycloakTokenError("Compte désactivé.", code="user_inactive")
    activity_stamp(user, mfa=identity.mfa)
    return user_attach_identity(user, identity), identity


# --- DRF --------------------------------------------------------------------------------


class KeycloakJWTAuthentication(BaseAuthentication):
    www_authenticate_realm = "jangubi"

    def authenticate(self, request: Any) -> tuple[Any, KeycloakIdentity] | None:
        parts = get_authorization_header(request).split()
        if len(parts) != 2 or parts[0].lower() != b"bearer":
            return None
        token = parts[1].decode("latin-1")
        # Déjà validé par KeycloakProvisioningMiddleware pour ce même jeton : pas de 2ᵉ vérification.
        cached = getattr(getattr(request, "_request", request), "_keycloak_identity", None)
        identity = cached[1] if cached and cached[0] == token else None
        try:
            return authenticate_token(token, identity)
        except KeycloakTokenError as exc:
            raise exceptions.AuthenticationFailed(str(exc), code=exc.code) from exc

    def authenticate_header(self, request: Any) -> str:
        return f'Bearer realm="{self.www_authenticate_realm}"'


def request_identity(request_or_user: Any) -> KeycloakIdentity | None:
    user = getattr(request_or_user, "user", request_or_user)
    return getattr(user, "keycloak_identity", None)
