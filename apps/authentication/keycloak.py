"""Validation des jetons d'accès Keycloak (OIDC) et provisioning des personnes (EF-AUTH-01, -02, -05).

Un jeton est « Keycloak » si son émetteur (``iss``) est celui du realm. Sinon la classe
d'authentification s'efface et l'ancienne authentification (SimpleJWT) peut prendre la
main tant que ``LEGACY_JWT_ENABLED`` est vrai. Un jeton Keycloak invalide n'est jamais
rattrapé par l'ancienne authentification : 401.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
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
    )


# --- Provisioning (EF-AUTH-02) -----------------------------------------------------------


@transaction.atomic
def person_from_identity(identity: KeycloakIdentity) -> Any:
    """Personne liée au ``sub`` ; à défaut, compte existant de même e-mail **vérifié**
    (comptes migrés) ; sinon création d'un fidèle. Idempotent."""
    from apps.users.enums import UserOnboardingState, UserRole

    User = get_user_model()
    person = User.objects.filter(keycloak_sub=identity.sub).first()
    if person is not None:
        return person
    if identity.email and identity.email_verified:
        person = User.objects.select_for_update().filter(email__iexact=identity.email, keycloak_sub__isnull=True).first()
        if person is not None:
            person.keycloak_sub = identity.sub
            person.save(update_fields=["keycloak_sub", "updated_at"])
            return person
    if not identity.email:
        raise KeycloakTokenError("Le jeton ne contient pas d'adresse e-mail.", code="email_missing")
    if User.objects.filter(email__iexact=identity.email).exists():
        # Compte existant mais e-mail non vérifié côté Keycloak (ou déjà lié ailleurs) :
        # jamais de rattachement, sinon prise de compte par simple inscription.
        raise KeycloakTokenError("Un compte existe déjà avec cette adresse.", code="email_conflict")
    try:
        with transaction.atomic():
            person = User.objects.create_user(
                email=identity.email,
                role=UserRole.FIDELE,
                phone_number=None,
                password=None,
                is_active=True,
                is_verified=identity.email_verified,
                keycloak_sub=identity.sub,
                onboarding_state=UserOnboardingState.PENDING_PARISH_SELECTION,
            )
    except IntegrityError as exc:
        # Course entre deux premières requêtes simultanées, ou e-mail déjà pris par un
        # compte non vérifié : on relit par sub, sinon on refuse (pas de prise de compte).
        person = User.objects.filter(keycloak_sub=identity.sub).first()
        if person is None:
            raise KeycloakTokenError("Un compte existe déjà avec cette adresse.", code="email_conflict") from exc
        return person
    _profile_ensure(person, identity)
    return person


def _profile_ensure(person: Any, identity: KeycloakIdentity) -> None:
    from apps.users.models import Profile

    Profile.objects.get_or_create(
        user=person,
        defaults={"first_name": identity.given_name[:50], "last_name": identity.family_name[:50]},
    )


def user_attach_identity(user: Any, identity: KeycloakIdentity) -> Any:
    """Porte les rôles de realm et la MFA sur l'objet utilisateur de la requête."""
    user.keycloak_identity = identity
    return user


def authenticate_token(token: str) -> tuple[Any, KeycloakIdentity]:
    identity = token_validate(token)
    user = person_from_identity(identity)
    if not user.is_active:
        raise KeycloakTokenError("Compte désactivé.", code="user_inactive")
    return user_attach_identity(user, identity), identity


# --- DRF --------------------------------------------------------------------------------


class KeycloakJWTAuthentication(BaseAuthentication):
    www_authenticate_realm = "jangubi"

    def authenticate(self, request: Any) -> tuple[Any, KeycloakIdentity] | None:
        if not settings.KEYCLOAK_ENABLED:
            return None
        parts = get_authorization_header(request).split()
        if len(parts) != 2 or parts[0].lower() != b"bearer":
            return None
        token = parts[1].decode("latin-1")
        if not is_keycloak_token(token):
            return None  # jeton SimpleJWT : l'ancienne authentification décide
        try:
            return authenticate_token(token)
        except KeycloakTokenError as exc:
            raise exceptions.AuthenticationFailed(str(exc), code=exc.code) from exc

    def authenticate_header(self, request: Any) -> str:
        return f'Bearer realm="{self.www_authenticate_realm}"'


def request_identity(request_or_user: Any) -> KeycloakIdentity | None:
    user = getattr(request_or_user, "user", request_or_user)
    return getattr(user, "keycloak_identity", None)
