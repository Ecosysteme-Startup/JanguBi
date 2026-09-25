"""
Services utilisateurs — toute la logique métier en écriture.
Conforme HackSoftware Django Styleguide + document OTP.

Flows couverts :
  1. Inscription fidèle (auto-inscription publique)
  2. Création de compte par super_admin → email avec mot de passe temporaire
  3. Activation de compte via token email
  4. Activation / désactivation de compte (admin)
  5. Soft delete / Hard delete
  6. Mise à jour profil (propriétaire ou admin)
  7. Changement de mot de passe (utilisateur connecté)
  8. Réinitialisation de mot de passe (oublié) — Magic Link
  9. Changement d'email — OTP double vérification + notification + réversion
"""

import logging
import secrets
import time
from typing import Any

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from apps.common.services import model_update
from apps.core.exceptions import ApplicationError, TokenInvalidError
from apps.emails.services import send_multi_format_email
from apps.users.enums import AuditEvent, UserOnboardingState, UserRole
from apps.users.models import BaseUser, Profile, SecurityAuditLog
from apps.users.otp import (
    RESET_TOKEN_TTL,
    REVERT_TOKEN_TTL,
    VERIFY_TOKEN_TTL,
    generate_otp_code,
    generate_url_token,
    otp_store,
    otp_verify,
    rate_limit_check,
    token_consume,
    token_store,
)

logger = logging.getLogger(__name__)

_ADMIN_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.PROVINCE_ADMIN,
    UserRole.DIOCESE_ADMIN,
    UserRole.PARISH_ADMIN,
    UserRole.CHURCH_ADMIN,
}


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------

@transaction.atomic
def user_create(
    *,
    email: str,
    password: str | None = None,
    role: str = UserRole.FIDELE,
    phone_number: str | None = None,
    is_active: bool = True,
    is_verified: bool = True,
    is_staff: bool = False,
    is_admin: bool = False,
) -> BaseUser:
    """Helper de compatibilité pour les tests legacy."""
    if phone_number is None:
        phone_number = f"+22177{secrets.randbelow(10**7):07d}"

    return BaseUser.objects.create_user(
        email=email,
        phone_number=phone_number,
        role=role,
        password=password,
        is_active=is_active,
        is_verified=is_verified,
        is_staff=is_staff,
        is_admin=is_admin,
    )


def _audit(
    user: BaseUser | None,
    event: str,
    ip: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Crée une entrée dans SecurityAuditLog. Ne lève jamais d'exception."""
    try:
        SecurityAuditLog.objects.create(
            user=user,
            event=event,
            ip_address=ip,
            metadata=metadata or {},
        )
    except Exception:
        logger.exception("Impossible de créer un SecurityAuditLog.")


def _send_email_safe(template_prefix: str, ctx: dict, to: str, path_prefix: str = "auth") -> None:
    """Envoi d'email non-bloquant : loggue l'erreur sans faire planter le service."""
    from django.conf import settings as django_settings
    full_ctx = {
        "frontend_url": getattr(django_settings, "FRONTEND_URL", "http://localhost:3000"),
        **ctx,
    }
    try:
        send_multi_format_email(
            template_prefix=template_prefix,
            template_ctxt=full_ctx,
            target_email=to,
            path_prefix=path_prefix,
        )
    except Exception:
        logger.exception(f"Échec envoi email '{template_prefix}' → {to}")


def _build_url(path: str) -> str:
    """Construit une URL absolue depuis FRONTEND_URL. Protection contre Host Header Injection."""
    from django.conf import settings
    FRONTEND_URL = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
    base = f"{FRONTEND_URL}/auth".rstrip("/")
    return f"{base}/{path.lstrip('/')}"


def _dummy_delay() -> None:
    """Délai artificiel pour égaliser les temps de réponse (anti-énumération)."""
    time.sleep(secrets.randbelow(150) / 1000 + 0.05)  # 50–200 ms


def _assign_group(user: BaseUser, role: str) -> None:
    """Assigne le Django Group correspondant au rôle. Crée le groupe si absent."""
    group, _ = Group.objects.get_or_create(name=role)
    user.groups.add(group)


# ---------------------------------------------------------------------------
# 1. Inscription fidèle (auto-inscription publique)
# ---------------------------------------------------------------------------

@transaction.atomic
def user_register_fidele(
    *,
    email: str,
    phone_number: str,
    password: str,
    first_name: str,
    last_name: str,
    title: str,
    ip: str | None = None,
) -> BaseUser | None:
    """
    Inscrit un fidèle (``None`` si l'adresse existe déjà : voir l'anti-énumération).
    Compte créé inactif + non-vérifié → email de vérification envoyé.
    Le groupe Django 'fidele' est assigné à l'activation du compte.
    """
    # Anti-énumération : être inscrit révèle une appartenance religieuse (donnée sensible).
    # Même réponse que pour une création ; la personne concernée est prévenue par e-mail.
    existing = BaseUser.objects.filter(email__iexact=email).first()
    if existing is not None:
        # Même travail coûteux que l'autre branche (validation + hachage) : pas d'écart de temps.
        try:
            validate_password(password)
        except DjangoValidationError as exc:
            raise ApplicationError(" ".join(exc.messages))
        make_password(password)
        _send_email_safe("account_exists", {"user": existing}, existing.email)
        return None

    try:
        validate_password(password)
    except DjangoValidationError as exc:
        raise ApplicationError(" ".join(exc.messages))

    user = BaseUser.objects.create_user(
        email=email,
        phone_number=phone_number,
        role=UserRole.FIDELE,
        password=password,
        is_active=False,
        is_verified=False,
    )

    Profile.objects.create(user=user, first_name=first_name, last_name=last_name, title=title)

    _audit(user, AuditEvent.REGISTER, ip)

    token = generate_url_token()
    token_store("email_verify", token, {"user_id": user.id}, ttl=VERIFY_TOKEN_TTL)

    _send_email_safe(
        "email_verification",
        {
            "user": user,
            "verification_url": _build_url(f"verify-email?token={token}"),
        },
        user.email,
    )

    return user


# ---------------------------------------------------------------------------
# 2. Création par super_admin
# ---------------------------------------------------------------------------

@transaction.atomic
def user_create_by_admin(
    *,
    email: str,
    phone_number: str,
    role: str,
    first_name: str,
    last_name: str,
    title: str = "",
    performed_by: BaseUser,
    ip: str | None = None,
) -> BaseUser:
    """
    Crée un compte avec le rôle choisi. Réservé au super_admin.
    Mot de passe temporaire généré + envoyé par email.
    Si aucune connexion dans ADMIN_ACCOUNT_EXPIRY_DAYS jours → purge via Celery Beat.
    """
    if performed_by.role != UserRole.SUPER_ADMIN:
        raise ApplicationError("Seul un Super Admin peut créer des comptes.")

    if role not in UserRole.values:
        raise ApplicationError(f"Rôle invalide : {role}")

    if BaseUser.objects.filter(email__iexact=email).exists():
        raise ApplicationError("Un compte avec cet email existe déjà.")

    temp_password = secrets.token_urlsafe(12)

    is_admin_role = role in _ADMIN_ROLES

    user = BaseUser.objects.create_user(
        email=email,
        phone_number=phone_number,
        role=role,
        password=temp_password,
        is_active=True,
        is_verified=True,
        is_staff=is_admin_role,
        is_admin=is_admin_role,
    )

    Profile.objects.create(user=user, first_name=first_name, last_name=last_name, title=title)

    _assign_group(user, role)

    _audit(user, AuditEvent.ADMIN_CREATED_ACCOUNT, ip, {"created_by": performed_by.email})

    _send_email_safe(
        "admin_created_account",
        {
            "user": user,
            "temp_password": temp_password,
            "login_url": _build_url("login"),
            "created_by": performed_by.email,
        },
        user.email,
    )

    return user


# ---------------------------------------------------------------------------
# 3. Activation de compte (token email)
# ---------------------------------------------------------------------------

@transaction.atomic
def user_activate_account(*, token: str, ip: str | None = None) -> BaseUser:
    """
    Active le compte via le token reçu par email.
    Anti-replay : le token est consommé (supprimé de Redis) dès usage.
    Assigne le groupe Django 'fidele' à l'activation.
    """
    payload = token_consume("email_verify", token)
    if payload is None:
        raise TokenInvalidError("Lien d'activation invalide ou expiré.")

    user_id = payload.get("user_id")
    if user_id is None:
        raise TokenInvalidError("Compte introuvable.")
    try:
        user = BaseUser.objects.get(id=user_id)
    except BaseUser.DoesNotExist:
        raise TokenInvalidError("Compte introuvable.")

    if user.is_verified and user.is_active:
        return user

    user.is_verified = True
    user.is_active = True
    update_fields = ["is_verified", "is_active", "updated_at"]

    # Vérif email franchie → étape suivante : sélection de la paroisse.
    if user.onboarding_state == UserOnboardingState.PENDING_EMAIL_VERIFICATION:
        user.onboarding_state = UserOnboardingState.PENDING_PARISH_SELECTION
        update_fields.append("onboarding_state")

    user.save(update_fields=update_fields)

    _assign_group(user, UserRole.FIDELE)
    _audit(user, AuditEvent.EMAIL_VERIFIED, ip)

    return user


# ---------------------------------------------------------------------------
# 4. Activation / désactivation (admin)
# ---------------------------------------------------------------------------

@transaction.atomic
def user_toggle_active(
    *,
    user: BaseUser,
    is_active: bool,
    performed_by: BaseUser,
    ip: str | None = None,
) -> BaseUser:
    """Active ou désactive un compte. Réservé aux rôles admin, dans leur périmètre."""
    from apps.users.selectors import user_is_in_scope_of

    if performed_by.role not in _ADMIN_ROLES:
        raise ApplicationError("Permission refusée.")

    # Cloisonnement territorial : sans cette garde, un admin diocésain pouvait
    # désactiver n'importe quel compte de la plateforme, y compris hors de son
    # diocèse et jusqu'aux responsables d'autres territoires.
    if not user_is_in_scope_of(target=user, admin=performed_by):
        raise ApplicationError("Cet utilisateur n'appartient pas à votre périmètre.")

    if user == performed_by:
        raise ApplicationError("Vous ne pouvez pas modifier votre propre statut d'activation.")

    user.is_active = is_active
    user.save(update_fields=["is_active", "updated_at"])

    event = AuditEvent.ACCOUNT_ACTIVATED if is_active else AuditEvent.ACCOUNT_DEACTIVATED
    _audit(user, event, ip, {"performed_by": performed_by.email})

    return user


# ---------------------------------------------------------------------------
# 5. Suppression
# ---------------------------------------------------------------------------

@transaction.atomic
def user_soft_delete(
    *,
    user: BaseUser,
    performed_by: BaseUser,
    ip: str | None = None,
) -> BaseUser:
    """Suppression douce : désactive + anonymise les données personnelles.

    Opération IRRÉVERSIBLE sur l'identité (email, téléphone, nom écrasés, mot de
    passe invalidé, session révoquée) : elle exige donc soit d'agir sur son
    propre compte, soit une autorité territoriale réelle sur la personne visée.
    """
    from apps.users.selectors import user_is_in_scope_of

    if performed_by != user:
        if performed_by.role not in _ADMIN_ROLES:
            raise ApplicationError("Permission refusée.")
        if not user_is_in_scope_of(target=user, admin=performed_by):
            raise ApplicationError("Cet utilisateur n'appartient pas à votre périmètre.")

    user.is_active = False
    user.email = f"deleted_{user.id}@deleted.invalid"
    user.phone_number = f"+221{str(user.id).replace('-', '')[:11]}"
    user.set_unusable_password()
    user.rotate_jwt_key()
    user.save(update_fields=["is_active", "email", "phone_number", "password", "jwt_key", "updated_at"])

    if hasattr(user, "profile"):
        profile = user.profile
        profile.first_name = ""
        profile.last_name = ""
        profile.save(update_fields=["first_name", "last_name", "updated_at"])

    _audit(user, AuditEvent.ACCOUNT_SOFT_DELETED, ip, {"performed_by": performed_by.email})

    return user


@transaction.atomic
def user_hard_delete(
    *,
    user: BaseUser,
    performed_by: BaseUser,
    ip: str | None = None,
) -> None:
    """Suppression définitive. Réservé au super_admin."""
    if performed_by.role != UserRole.SUPER_ADMIN:
        raise ApplicationError("Seul un Super Admin peut supprimer définitivement un compte.")

    if user == performed_by:
        raise ApplicationError("Vous ne pouvez pas supprimer votre propre compte.")

    user_email = user.email
    user_id = user.id

    _audit(user, AuditEvent.ACCOUNT_HARD_DELETED, ip, {
        "performed_by": performed_by.email,
        "deleted_email": user_email,
        "deleted_id": str(user_id),
    })

    user.delete()


# ---------------------------------------------------------------------------
# 6. Mise à jour profil
# ---------------------------------------------------------------------------

def _onboard_via_primary_parish_shim(*, user: BaseUser, parish_id: int | None) -> None:
    """COMPAT (Chantier 2 — début du cutover).

    Le PATCH legacy `primary_parish` (id scalaire, envoyé par le front actuel) ne
    touche plus `Profile.primary_parish` en direct : il crée/promeut une Membership
    PRINCIPALE sur l'église principale (`is_main`) de la paroisse. Le signal Membership
    miroir ensuite `primary_parish` + `diocese`/`province`, et l'onboarding est
    recalculé depuis les appartenances.

    Pas de repli silencieux : paroisse introuvable ou sans église principale → erreur.
    """
    if parish_id is None:
        # Le front legacy ne désélectionne jamais la paroisse → no-op.
        return

    from apps.org.models import Church, Parish
    from apps.users.models import Membership
    from apps.users.services_memberships import membership_create, membership_set_primary

    try:
        parish = Parish.objects.get(pk=parish_id)
    except Parish.DoesNotExist:
        raise ApplicationError("Paroisse introuvable.")

    main_church = Church.objects.filter(parish=parish, is_main=True).first()
    if main_church is None:
        raise ApplicationError("Cette paroisse n'a pas d'église principale.")

    existing = Membership.objects.filter(user=user, church=main_church).first()
    if existing is not None:
        membership_set_primary(user=user, membership=existing)
    else:
        membership_create(user=user, church=main_church, is_primary=True)


@transaction.atomic
def user_update_profile(
    *,
    user: BaseUser,
    data: dict[str, Any],
    performed_by: BaseUser,
    ip: str | None = None,
) -> BaseUser:
    """Met à jour les données de profil. Propriétaire ou admin."""
    if performed_by != user and performed_by.role not in _ADMIN_ROLES:
        raise ApplicationError("Permission refusée.")

    profile_fields = ["first_name", "last_name", "title", "date_of_birth", "phone"]

    profile, _ = Profile.objects.get_or_create(user=user)
    profile, _ = model_update(instance=profile, fields=profile_fields, data=data)

    # COMPAT : la paroisse principale (id scalaire legacy) est ROUTÉE vers une
    # Membership principale (shim Chantier 2). Le signal Membership + le recalcul
    # d'onboarding font le reste (miroir primary_parish, diocese/province, completed).
    if "primary_parish" in data:
        _onboard_via_primary_parish_shim(user=user, parish_id=data["primary_parish"])

    if "avatar" in data and data["avatar"] is not None:
        profile.avatar = data["avatar"]
        profile.save(update_fields=["avatar"])

    # Le signal Membership remplit diocese/province + onboarding_state via queryset
    # .update()/.save() hors de l'objet en mémoire selon le chemin. On recharge pour
    # que la réponse (PATCH /me) reflète immédiatement la hiérarchie territoriale.
    if "primary_parish" in data:
        user.refresh_from_db()

    _audit(user, AuditEvent.PROFILE_UPDATED, ip, {"performed_by": performed_by.email})

    return user


# ---------------------------------------------------------------------------
# 7. Changement de mot de passe (utilisateur connecté)
# ---------------------------------------------------------------------------

@transaction.atomic
def password_change(
    *,
    user: BaseUser,
    current_password: str,
    new_password: str,
    ip: str | None = None,
) -> None:
    """
    Change le mot de passe d'un utilisateur authentifié.
    Invalide TOUS les JWT actifs via rotation du jwt_key.
    """
    if not user.check_password(current_password):
        raise ApplicationError("Mot de passe actuel incorrect.")

    try:
        validate_password(new_password, user=user)
    except DjangoValidationError as exc:
        raise ApplicationError(" ".join(exc.messages))

    if current_password == new_password:
        raise ApplicationError("Le nouveau mot de passe doit être différent de l'ancien.")

    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    user.rotate_jwt_key()

    _audit(user, AuditEvent.PASSWORD_CHANGED, ip)

    _send_email_safe("password_changed_notification", {"user": user}, user.email)


# ---------------------------------------------------------------------------
# 8. Réinitialisation de mot de passe (oublié) — Magic Link
# ---------------------------------------------------------------------------

@transaction.atomic
def password_reset_request(*, email: str, ip: str | None = None) -> None:
    """
    Envoie un lien de réinitialisation si l'email est enregistré.
    Réponse TOUJOURS identique (anti-énumération).
    """
    rate_limit_check("pwd_reset", ip, limit=5)

    try:
        user = BaseUser.objects.get(email__iexact=email, is_active=True)
    except BaseUser.DoesNotExist:
        _dummy_delay()
        return

    token = generate_url_token()
    token_store("pwd_reset", token, {"user_id": user.id}, ttl=RESET_TOKEN_TTL)

    _audit(user, AuditEvent.PASSWORD_RESET_REQUEST, ip)

    _send_email_safe(
        "password_reset",
        {
            "user": user,
            "reset_url": _build_url(f"reset-password?token={token}"),
            "ttl_minutes": RESET_TOKEN_TTL // 60,
        },
        user.email,
    )


@transaction.atomic
def verification_email_resend(*, email: str, ip: str | None = None) -> None:
    """
    Renvoie le lien de vérification à un compte encore inactif.

    Un compte est créé `is_active=False` et n'est activé que par ce lien, valable
    24 h. Sans renvoi, un testeur ayant perdu son email restait bloqué pour
    toujours : la réinscription est refusée (« un compte avec cet email existe
    déjà »), et aucune autre issue n'existait qu'une intervention en base.

    Réponse TOUJOURS identique, que le compte existe, soit déjà vérifié ou non
    (anti-énumération) — même contrat que `password_reset_request`.
    """
    rate_limit_check("email_verify_resend", ip, limit=5)

    try:
        user = BaseUser.objects.get(email__iexact=email, is_verified=False)
    except BaseUser.DoesNotExist:
        # Compte inexistant OU déjà vérifié : rien à renvoyer, et surtout rien
        # à révéler. On imite le coût d'un envoi réel.
        _dummy_delay()
        return

    token = generate_url_token()
    token_store("email_verify", token, {"user_id": user.id}, ttl=VERIFY_TOKEN_TTL)

    _send_email_safe(
        "email_verification",
        {
            "user": user,
            "verification_url": _build_url(f"verify-email?token={token}"),
        },
        user.email,
    )


@transaction.atomic
def password_reset_confirm(
    *,
    token: str,
    new_password: str,
    ip: str | None = None,
) -> None:
    """Valide le token et applique le nouveau mot de passe. Anti-replay."""
    payload = token_consume("pwd_reset", token)
    if payload is None:
        raise TokenInvalidError("Lien de réinitialisation invalide ou expiré.")

    try:
        user = BaseUser.objects.get(id=payload["user_id"])
    except BaseUser.DoesNotExist:
        raise TokenInvalidError("Compte introuvable.")

    try:
        validate_password(new_password, user=user)
    except DjangoValidationError as exc:
        raise ApplicationError(" ".join(exc.messages))

    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    user.rotate_jwt_key()

    _audit(user, AuditEvent.PASSWORD_RESET_CONFIRM, ip)

    _send_email_safe("password_changed_notification", {"user": user}, user.email)


# ---------------------------------------------------------------------------
# 9. Changement d'email — OTP double vérification
# ---------------------------------------------------------------------------

@transaction.atomic
def email_change_request(
    *,
    user: BaseUser,
    new_email: str,
    current_password: str,
    ip: str | None = None,
) -> None:
    """Étape 1 : demande de changement d'email. Sudo Mode + OTP à la NOUVELLE adresse."""
    rate_limit_check("email_change", ip, limit=3)

    if not user.check_password(current_password):
        raise ApplicationError("Mot de passe incorrect.")

    if new_email.lower() == user.email.lower():
        raise ApplicationError("La nouvelle adresse est identique à l'adresse actuelle.")

    if BaseUser.objects.filter(email__iexact=new_email).exists():
        raise ApplicationError("Cette adresse email est déjà utilisée par un autre compte.")

    code = generate_otp_code()
    otp_store(user.id, "email_change", code)

    from django.core.cache import cache
    cache.set(f"email_change_pending:{user.id}", new_email, timeout=600)

    _audit(user, AuditEvent.EMAIL_CHANGE_REQUEST, ip, {
        "new_email_masked": f"{new_email[:2]}***@{new_email.split('@')[-1]}"
    })

    _send_email_safe(
        "email_change_otp",
        {"user": user, "otp_code": code, "ttl_minutes": 10},
        new_email,
    )


@transaction.atomic
def email_change_confirm(
    *,
    user: BaseUser,
    otp_code: str,
    ip: str | None = None,
) -> None:
    """Étape 2 : validation OTP + application du changement. Rotation du jwt_key."""
    from django.core.cache import cache

    otp_verify(user.id, "email_change", otp_code)

    new_email = cache.get(f"email_change_pending:{user.id}")
    if not new_email:
        raise ApplicationError("Session de changement d'email expirée. Recommencez.")

    cache.delete(f"email_change_pending:{user.id}")

    old_email = user.email

    if BaseUser.objects.filter(email__iexact=new_email).exclude(id=user.id).exists():
        raise ApplicationError("Cette adresse email vient d'être prise par un autre compte.")

    user.email = new_email
    user.save(update_fields=["email", "updated_at"])
    user.rotate_jwt_key()

    _audit(user, AuditEvent.EMAIL_CHANGE_CONFIRM, ip, {
        "old_email_masked": f"{old_email[:2]}***@{old_email.split('@')[-1]}",
        "new_email_masked": f"{new_email[:2]}***@{new_email.split('@')[-1]}",
    })

    revert_token = generate_url_token()
    token_store("email_revert", revert_token, {
        "user_id": user.id,
        "old_email": old_email,
    }, ttl=REVERT_TOKEN_TTL)

    _send_email_safe(
        "email_change_notification",
        {
            "user": user,
            "old_email": old_email,
            "new_email": new_email,
            "revert_url": _build_url(f"revert-email?token={revert_token}"),
            "revert_days": REVERT_TOKEN_TTL // 86400,
        },
        old_email,
    )


@transaction.atomic
def email_change_revert(*, token: str, ip: str | None = None) -> BaseUser:
    """Réversion d'urgence d'un changement d'email. Accessible sans authentification."""
    payload = token_consume("email_revert", token)
    if payload is None:
        raise TokenInvalidError("Lien de réversion invalide ou expiré.")

    try:
        user = BaseUser.objects.get(id=payload["user_id"])
    except BaseUser.DoesNotExist:
        raise TokenInvalidError("Compte introuvable.")

    old_email = payload["old_email"]
    current_email = user.email

    if user.email.lower() == old_email.lower():
        return user

    if BaseUser.objects.filter(email__iexact=old_email).exclude(id=user.id).exists():
        raise ApplicationError(
            "L'ancienne adresse email ne peut pas être restaurée (déjà utilisée)."
        )

    user.email = old_email
    user.set_unusable_password()
    user.save(update_fields=["email", "password", "updated_at"])
    user.rotate_jwt_key()

    _audit(user, AuditEvent.EMAIL_CHANGE_REVERTED, ip, {
        "reverted_from": f"{current_email[:2]}***@{current_email.split('@')[-1]}",
        "restored_to": f"{old_email[:2]}***@{old_email.split('@')[-1]}",
    })

    return user


@transaction.atomic
def purge_expired_unactivated_admin_accounts(*, expiry_days: int) -> int:
    """Delete admin accounts that were created but never activated within the expiry window."""
    from datetime import timedelta

    from django.utils import timezone

    cutoff = timezone.now() - timedelta(days=expiry_days)
    qs = BaseUser.objects.filter(
        role__in=list(_ADMIN_ROLES),
        last_login__isnull=True,
        created_at__lt=cutoff,
    )
    count, _ = qs.delete()
    return count
