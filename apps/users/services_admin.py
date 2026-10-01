"""Administration des comptes, synchronisée avec Keycloak (docs/ADMIN-KEYCLOAK.md).

Chaque service :
- vérifie la portée (``scope_admin``) : plateforme > diocèse > paroisse, jamais au-dessus ;
- écrit dans Keycloak **dans la même transaction** que la base : si Keycloak refuse ou ne
  répond pas, l'exception annule la transaction (rien n'est écrit côté application) ; une
  création déjà faite dans Keycloak est compensée (supprimée) si la base échoue ensuite ;
- journalise l'action dans l'audit (``compte.admin.*`` : qui, quoi, quand, sur qui, motif).

Garde-fous : jamais de mot de passe saisi par un administrateur (Keycloak envoie un lien) ;
jamais d'usurpation d'identité (impersonation) ; motif obligatoire pour les actions sensibles ;
pas d'action destructive sur son propre compte ; jamais de retrait du dernier administrateur
plateforme.
"""

import logging
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.authentication.keycloak_admin import (
    KeycloakAdminError,
    KeycloakBadRequestError,
    KeycloakConflictError,
    KeycloakForbiddenError,
    KeycloakNotFoundError,
)
from apps.core.exceptions import ApplicationError, ConflictError, PermissionDeniedError
from apps.hierarchy import authz
from apps.hierarchy.audit import audit_log
from apps.hierarchy.enums import DegreOrdre, EtatDeVie, StatutVerification
from apps.hierarchy.models import Node
from apps.integrations.keycloak import get_keycloak_admin
from apps.integrations.keycloak.client import REQUIRED_ACTIONS
from apps.users import scope_admin
from apps.users.models import BaseUser, Profile
from apps.users.services_keycloak_sync import account_pull, keycloak_representation
from apps.users.services_privacy import account_erase, account_has_active_offices, account_is_erased

logger = logging.getLogger(__name__)

INVITATION_ACTIONS = ["VERIFY_EMAIL", "UPDATE_PASSWORD"]
REASON_MIN_LENGTH = 5


class KeycloakServiceError(ApplicationError):
    code = "keycloak_unavailable"
    status_code = 503


# --- Outils ---------------------------------------------------------------------------------


def _client() -> Any:
    if not settings.KEYCLOAK_ENABLED:
        raise KeycloakServiceError("La synchronisation avec Keycloak est désactivée : action impossible.")
    return get_keycloak_admin()


def _kc(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Appel Keycloak, erreurs traduites en erreurs métier (la transaction est annulée)."""
    try:
        return fn(*args, **kwargs)
    except KeycloakConflictError as exc:
        raise ConflictError("Cette adresse e-mail est déjà utilisée dans Keycloak.", code="keycloak_conflict") from exc
    except KeycloakNotFoundError as exc:
        raise ConflictError(
            "Ce compte n'existe plus dans Keycloak : lancez une resynchronisation.", code="keycloak_not_found"
        ) from exc
    except KeycloakForbiddenError as exc:
        raise KeycloakServiceError(
            "Le compte de service Keycloak n'a pas les droits nécessaires.", code="keycloak_forbidden"
        ) from exc
    except KeycloakBadRequestError as exc:
        raise ApplicationError("Keycloak a refusé la demande.", code="keycloak_bad_request") from exc
    except KeycloakAdminError as exc:
        raise KeycloakServiceError("Keycloak n'a pas pu exécuter l'action. Réessayez plus tard.") from exc


def _linked(account: BaseUser) -> str:
    if account_is_erased(account):
        raise ApplicationError("Ce compte a été supprimé.", code="account_deleted")
    if not account.keycloak_sub:
        raise ConflictError(
            "Ce compte n'est pas encore lié à Keycloak : lancez une resynchronisation.", code="account_not_linked"
        )
    return account.keycloak_sub


def _reason(reason: str) -> str:
    reason = " ".join((reason or "").split())
    if len(reason) < REASON_MIN_LENGTH:
        raise ApplicationError("Indiquez le motif de cette action.", code="reason_required")
    return reason[:255]


def _not_self(actor: Any, account: BaseUser) -> None:
    if account.pk == getattr(actor, "pk", None):
        raise PermissionDeniedError("Action impossible sur votre propre compte.", code="self_action")


def _audit(
    *, actor: Any, account: BaseUser, action: str, ip: str | None, metadata: dict[str, Any] | None = None
) -> None:
    audit_log(
        actor=actor,
        action=f"compte.admin.{action}",
        target=account,
        node=scope_admin.primary_node(account),
        metadata=metadata or {},
        ip=ip,
    )


def _invalidate_directory() -> None:
    from apps.users.keycloak_accounts import keycloak_directory_invalidate

    keycloak_directory_invalidate()


def _manageable(actor: Any, account: BaseUser) -> str:
    scope_admin.require_manage(actor, account)
    return _linked(account)


def keycloak_actions_email_send(*, keycloak_id: str, actions: list[str]) -> None:
    kwargs: dict[str, Any] = {"lifespan": settings.KEYCLOAK_ACTIONS_EMAIL_LIFESPAN}
    if settings.KEYCLOAK_ACTIONS_CLIENT_ID and settings.KEYCLOAK_ACTIONS_REDIRECT_URI:
        kwargs["client_id"] = settings.KEYCLOAK_ACTIONS_CLIENT_ID
        kwargs["redirect_uri"] = settings.KEYCLOAK_ACTIONS_REDIRECT_URI
    get_keycloak_admin().execute_actions_email(keycloak_id, list(actions), **kwargs)


def _actions_email_on_commit(keycloak_id: str, actions: list[str]) -> None:
    from apps.users.tasks import keycloak_actions_email_task

    transaction.on_commit(lambda: keycloak_actions_email_task.delay(keycloak_id, list(actions)))


# --- Création -------------------------------------------------------------------------------


def account_admin_create(
    *,
    actor: Any,
    email: str,
    node: Node,
    first_name: str = "",
    last_name: str = "",
    phone_number: str | None = None,
    etat_de_vie: str = EtatDeVie.LAIC,
    degre_ordre: str = DegreOrdre.AUCUN,
    send_invitation: bool = True,
    ip: str | None = None,
) -> BaseUser:
    """Crée le compte dans Keycloak puis dans l'application. Keycloak d'abord (il fournit
    l'identifiant) ; si la base échoue, le compte Keycloak créé est supprimé (compensation).
    Une adresse déjà présente dans Keycloak et inconnue de l'application est rattachée
    (idempotence), sans réinitialiser son mot de passe."""
    scope_admin.require_node(actor, node)
    email = (email or "").strip().lower()
    if BaseUser.objects.filter(email__iexact=email).exists():
        raise ConflictError("Un compte existe déjà avec cette adresse.", code="account_exists")
    if etat_de_vie == EtatDeVie.CLERC and degre_ordre == DegreOrdre.AUCUN:
        raise ApplicationError("Indiquez le degré d'ordre du clerc.", code="degre_ordre_required")
    if etat_de_vie != EtatDeVie.CLERC and degre_ordre != DegreOrdre.AUCUN:
        raise ApplicationError("Seul un clerc a un degré d'ordre.", code="degre_ordre_invalid")
    client = _client()
    representation = {
        "username": email,
        "email": email,
        "firstName": first_name.strip()[:50],
        "lastName": last_name.strip()[:50],
        "enabled": True,
        "emailVerified": False,
        "requiredActions": INVITATION_ACTIONS if send_invitation else [],
    }
    keycloak_id, created = _kc(client.user_create, representation)
    if not created and BaseUser.objects.filter(keycloak_sub=keycloak_id).exists():
        raise ConflictError("Ce compte Keycloak est déjà lié à un autre compte.", code="account_exists")
    existing = _kc(client.user_get, keycloak_id) if not created else representation
    try:
        with transaction.atomic():
            now = timezone.now()
            declared = etat_de_vie != EtatDeVie.LAIC
            user = BaseUser.objects.create_user(
                email=email,
                phone_number=phone_number or None,
                password=None,
                is_active=bool(existing.get("enabled", True)),
                is_verified=bool(existing.get("emailVerified", False)),
                keycloak_sub=keycloak_id,
                admin_node=node,
                etat_de_vie=etat_de_vie,
                degre_ordre=degre_ordre,
                statut_verification=StatutVerification.DECLARE if declared else StatutVerification.VERIFIE,
                declared_at=now if declared else None,
                keycloak_synced_at=now,
            )
            Profile.objects.create(user=user, first_name=first_name.strip()[:50], last_name=last_name.strip()[:50])
            _audit(
                actor=actor,
                account=user,
                action="creation",
                ip=ip,
                metadata={
                    "keycloak": "cree" if created else "rattache",
                    "invitation": bool(send_invitation and created),
                },
            )
            if send_invitation and created:
                _actions_email_on_commit(keycloak_id, INVITATION_ACTIONS)
    except (IntegrityError, ApplicationError, ValueError, Exception) as exc:
        if created:
            try:
                client.user_delete(keycloak_id)
            except KeycloakAdminError:
                logger.error("keycloak.admin.create_compensation_failed", extra={"keycloak_id": keycloak_id})
        if isinstance(exc, IntegrityError):
            raise ConflictError("Un compte existe déjà avec ces informations.", code="account_exists") from exc
        raise
    _invalidate_directory()
    return user


# --- Modification ---------------------------------------------------------------------------

UPDATABLE_FIELDS = ("email", "first_name", "last_name", "phone_number", "admin_node")


@transaction.atomic
def account_admin_update(*, actor: Any, account: BaseUser, data: dict[str, Any], ip: str | None = None) -> BaseUser:
    """Modifie l'identité (base puis Keycloak, même transaction). Un changement d'e-mail le
    rend « non vérifié » et Keycloak envoie un e-mail de vérification."""
    unknown = set(data) - set(UPDATABLE_FIELDS)
    if unknown:
        raise ApplicationError("Champs non modifiables.", {"fields": sorted(unknown)}, code="field_not_updatable")
    keycloak_id = _manageable(actor, account)
    account = BaseUser.objects.select_for_update().get(pk=account.pk)
    changed: list[str] = []
    user_fields: list[str] = []
    email_changed = False
    if "email" in data:
        email = (data["email"] or "").strip().lower()
        if email != account.email:
            if BaseUser.objects.filter(email__iexact=email).exclude(pk=account.pk).exists():
                raise ConflictError("Un compte existe déjà avec cette adresse.", code="account_exists")
            account.email = email
            account.is_verified = False
            user_fields += ["email", "is_verified"]
            email_changed = True
    if "phone_number" in data and (data["phone_number"] or None) != account.phone_number:
        account.phone_number = data["phone_number"] or None
        user_fields.append("phone_number")
    if "admin_node" in data and data["admin_node"] != account.admin_node:
        new_node = data["admin_node"]
        if new_node is not None:
            scope_admin.require_node(actor, new_node)
        elif not scope_admin.is_platform(actor):
            raise PermissionDeniedError(
                "Seule la plateforme peut détacher un compte de tout nœud.", code="platform_only"
            )
        account.admin_node = new_node
        user_fields.append("admin_node")
    if user_fields:
        try:
            account.full_clean(exclude=["password"])
        except Exception as exc:  # ValidationError de Django : format du téléphone, etc.
            raise ApplicationError("Informations invalides.", code="validation_error") from exc
        account.save(update_fields=[*user_fields, "updated_at"])
        changed += user_fields
    profile, _ = Profile.objects.get_or_create(user=account)
    profile_fields = []
    for name in ("first_name", "last_name"):
        if name in data and (data[name] or "").strip()[:50] != getattr(profile, name):
            setattr(profile, name, (data[name] or "").strip()[:50])
            profile_fields.append(name)
    if profile_fields:
        profile.save(update_fields=[*profile_fields, "updated_at"])
        changed += profile_fields
    if not changed:
        return account
    rep = keycloak_representation(account)
    fields = {"firstName": rep["firstName"], "lastName": rep["lastName"]}
    if email_changed:
        fields.update({"email": account.email, "username": account.email, "emailVerified": False})
    client = _client()
    if {"email", "first_name", "last_name"} & set(changed):
        _kc(client.user_update, keycloak_id, fields)
    if email_changed:
        _actions_email_on_commit(keycloak_id, ["VERIFY_EMAIL"])
    BaseUser.objects.filter(pk=account.pk).update(keycloak_synced_at=timezone.now(), keycloak_sync_error="")
    _audit(actor=actor, account=account, action="modification", ip=ip, metadata={"champs": sorted(changed)})
    _invalidate_directory()
    return account


# --- Activation ---------------------------------------------------------------------------


@transaction.atomic
def account_admin_set_active(
    *, actor: Any, account: BaseUser, active: bool, reason: str = "", ip: str | None = None
) -> BaseUser:
    """Désactive (motif obligatoire ; sessions fermées) ou réactive (blocage anti-force brute levé)."""
    keycloak_id = _manageable(actor, account)
    motif = _reason(reason) if not active else " ".join((reason or "").split())[:255]
    if not active:
        _not_self(actor, account)
        _last_platform_admin_guard(account)
    BaseUser.objects.filter(pk=account.pk).update(is_active=active, keycloak_synced_at=timezone.now())
    account.is_active = active
    client = _client()
    _kc(client.user_set_enabled, keycloak_id, active)
    if active:
        _kc(client.user_brute_force_reset, keycloak_id)
    else:
        _kc(client.user_logout, keycloak_id)
    authz.invalidate_user(account.pk)
    _audit(
        actor=actor,
        account=account,
        action="reactivation" if active else "desactivation",
        ip=ip,
        metadata={"motif": motif} if motif else {},
    )
    _invalidate_directory()
    return account


# --- Suppression (RGPD) -------------------------------------------------------------------


@transaction.atomic
def account_admin_delete(
    *, actor: Any, account: BaseUser, confirm_email: str, reason: str, ip: str | None = None
) -> None:
    """Anonymisation côté application puis suppression dans Keycloak, dans la même transaction :
    si Keycloak échoue, l'anonymisation est annulée. Une nomination en cours doit d'abord prendre fin."""
    scope_admin.require_manage(actor, account)
    _not_self(actor, account)
    if account_is_erased(account):
        raise ApplicationError("Ce compte a déjà été supprimé.", code="account_deleted")
    if (confirm_email or "").strip().lower() != account.email:
        raise ApplicationError("Recopiez l'adresse e-mail du compte pour confirmer.", code="confirmation_mismatch")
    motif = _reason(reason)
    _last_platform_admin_guard(account)
    if account_has_active_offices(account):
        raise ConflictError("Ce compte a une nomination en cours : mettez-y fin d'abord.", code="active_office")
    node = scope_admin.primary_node(account)
    account = BaseUser.objects.select_for_update().get(pk=account.pk)
    keycloak_id = account_erase(user=account, actor=actor, action="compte.admin.suppression", metadata={"motif": motif})
    if node is not None:
        from apps.hierarchy.models import AuditEvent

        AuditEvent.objects.filter(action="compte.admin.suppression", target_id=str(account.pk)).update(node=node)
    if keycloak_id and settings.KEYCLOAK_ENABLED:
        _kc(_client().user_delete, keycloak_id)
    _invalidate_directory()


# --- Actions Keycloak -----------------------------------------------------------------------


@transaction.atomic
def account_actions_email(*, actor: Any, account: BaseUser, actions: list[str], ip: str | None = None) -> BaseUser:
    """Keycloak envoie à la personne un lien pour exécuter les actions (nouveau mot de passe,
    vérification d'e-mail, second facteur…). L'administrateur ne saisit jamais de mot de passe."""
    keycloak_id = _manageable(actor, account)
    actions = list(dict.fromkeys(actions))
    if not actions or any(a not in REQUIRED_ACTIONS for a in actions):
        raise ApplicationError("Action requise inconnue.", {"allowed": list(REQUIRED_ACTIONS)}, code="invalid_action")
    kwargs: dict[str, Any] = {"lifespan": settings.KEYCLOAK_ACTIONS_EMAIL_LIFESPAN}
    if settings.KEYCLOAK_ACTIONS_CLIENT_ID and settings.KEYCLOAK_ACTIONS_REDIRECT_URI:
        kwargs["client_id"] = settings.KEYCLOAK_ACTIONS_CLIENT_ID
        kwargs["redirect_uri"] = settings.KEYCLOAK_ACTIONS_REDIRECT_URI
    _kc(_client().execute_actions_email, keycloak_id, actions, **kwargs)
    _audit(actor=actor, account=account, action="actions_email", ip=ip, metadata={"actions": actions})
    return account


def account_password_reset(*, actor: Any, account: BaseUser, ip: str | None = None) -> BaseUser:
    return account_actions_email(actor=actor, account=account, actions=["UPDATE_PASSWORD"], ip=ip)


@transaction.atomic
def account_verify_email_send(*, actor: Any, account: BaseUser, ip: str | None = None) -> BaseUser:
    keycloak_id = _manageable(actor, account)
    _kc(_client().send_verify_email, keycloak_id)
    _audit(actor=actor, account=account, action="verification_email_envoyee", ip=ip)
    return account


@transaction.atomic
def account_email_mark_verified(*, actor: Any, account: BaseUser, reason: str, ip: str | None = None) -> BaseUser:
    """Marque l'e-mail comme vérifié sans lien (plateforme seulement, motif obligatoire)."""
    scope_admin.require_platform(actor)
    keycloak_id = _manageable(actor, account)
    motif = _reason(reason)
    BaseUser.objects.filter(pk=account.pk).update(is_verified=True)
    account.is_verified = True
    _kc(_client().user_update, keycloak_id, {"emailVerified": True})
    _audit(actor=actor, account=account, action="email_marque_verifie", ip=ip, metadata={"motif": motif})
    _invalidate_directory()
    return account


@transaction.atomic
def account_sessions_logout(*, actor: Any, account: BaseUser, ip: str | None = None) -> BaseUser:
    keycloak_id = _manageable(actor, account)
    _kc(_client().user_logout, keycloak_id)
    _audit(actor=actor, account=account, action="deconnexion_sessions", ip=ip)
    return account


@transaction.atomic
def account_session_revoke(*, actor: Any, account: BaseUser, session_id: str, ip: str | None = None) -> BaseUser:
    keycloak_id = _manageable(actor, account)
    client = _client()
    sessions = _kc(client.user_sessions, keycloak_id)
    if not any(str(s.get("id")) == session_id for s in sessions):
        raise ApplicationError("Session introuvable pour ce compte.", code="session_not_found")
    _kc(client.session_delete, session_id)
    _audit(actor=actor, account=account, action="session_revoquee", ip=ip)
    return account


@transaction.atomic
def account_otp_reset(*, actor: Any, account: BaseUser, reason: str, ip: str | None = None) -> BaseUser:
    """Retire le second facteur (téléphone perdu…) et en exige un nouveau à la prochaine connexion."""
    keycloak_id = _manageable(actor, account)
    _not_self(actor, account)
    motif = _reason(reason)
    client = _client()
    removed = _kc(client.otp_reset, keycloak_id)
    _kc(client.add_required_action, keycloak_id, "CONFIGURE_TOTP")
    _kc(client.user_logout, keycloak_id)
    _audit(
        actor=actor, account=account, action="otp_reinitialise", ip=ip, metadata={"motif": motif, "retires": removed}
    )
    _invalidate_directory()
    return account


@transaction.atomic
def account_brute_force_unlock(*, actor: Any, account: BaseUser, ip: str | None = None) -> BaseUser:
    keycloak_id = _manageable(actor, account)
    _kc(_client().user_brute_force_reset, keycloak_id)
    _audit(actor=actor, account=account, action="deblocage_force_brute", ip=ip)
    return account


# --- Rôle platform_admin ------------------------------------------------------------------


def _last_platform_admin_guard(account: BaseUser) -> None:
    if not account.keycloak_platform_admin:
        return
    others = BaseUser.objects.filter(keycloak_platform_admin=True, is_active=True).exclude(pk=account.pk)
    if not others.exists():
        raise ConflictError("C'est le dernier administrateur plateforme.", code="last_platform_admin")


@transaction.atomic
def account_platform_admin_set(
    *, actor: Any, account: BaseUser, grant: bool, reason: str, ip: str | None = None
) -> BaseUser:
    """Donne ou retire le rôle de realm ``platform_admin`` (plateforme seulement, motif
    obligatoire, jamais sur soi-même, jamais le dernier). La MFA devient une action requise."""
    scope_admin.require_platform(actor)
    _not_self(actor, account)
    keycloak_id = _linked(account)
    motif = _reason(reason)
    if not grant:
        _last_platform_admin_guard(account)
    BaseUser.objects.filter(pk=account.pk).update(keycloak_platform_admin=grant)
    account.keycloak_platform_admin = grant
    client = _client()
    role = settings.KEYCLOAK_PLATFORM_ADMIN_ROLE
    if grant:
        _kc(client.add_realm_role, keycloak_id, role)
        if not _kc(client.user_has_otp, keycloak_id):
            _kc(client.add_required_action, keycloak_id, "CONFIGURE_TOTP")
    else:
        _kc(client.remove_realm_role, keycloak_id, role)
        _kc(client.user_logout, keycloak_id)  # le jeton en cours porte encore le rôle
    authz.invalidate_user(account.pk)
    _audit(
        actor=actor,
        account=account,
        action="role_plateforme_ajoute" if grant else "role_plateforme_retire",
        ip=ip,
        metadata={"motif": motif},
    )
    _invalidate_directory()
    return account


# --- Resynchronisation --------------------------------------------------------------------


def account_resync(*, actor: Any, account: BaseUser, ip: str | None = None) -> BaseUser:
    """Relit le compte dans Keycloak (qui fait foi pour l'identité) ; compte non lié : créé
    ou rattaché dans Keycloak."""
    from apps.users.services_keycloak_sync import account_push

    scope_admin.require_manage(actor, account)
    if account_is_erased(account):
        raise ApplicationError("Ce compte a été supprimé.", code="account_deleted")
    client = _client()
    if account.keycloak_sub:
        result = _kc(account_pull, keycloak_id=account.keycloak_sub, client=client).action
    else:
        result = _kc(account_push, user=account, client=client)
    _audit(actor=actor, account=account, action="resynchronisation", ip=ip, metadata={"resultat": result})
    _invalidate_directory()
    return BaseUser.objects.get(pk=account.pk)
