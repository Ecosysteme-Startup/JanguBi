"""Actions d'administration sur les comptes (``plateforme.admin``), exécutées dans Keycloak
par le compte de service ``jangubi-admin-sync`` et journalisées dans l'audit (EF-PER-11).

Chaque action est atomique : si Keycloak refuse ou ne répond pas, la base n'est pas modifiée
et aucune entrée d'audit n'est écrite.
"""

from typing import Any

from django.conf import settings
from django.db import transaction

from apps.core.exceptions import ApplicationError
from apps.hierarchy.audit import audit_log
from apps.users.keycloak_accounts import (
    KEYCLOAK_ERRORS,
    keycloak_admin_client,
    keycloak_directory_invalidate,
)
from apps.users.models import BaseUser

REQUIRED_ACTION_TOTP = "CONFIGURE_TOTP"


class KeycloakUnavailableError(ApplicationError):
    code = "keycloak_unavailable"
    status_code = 503


def _keycloak_id(account: BaseUser, *, required: bool) -> str | None:
    if not settings.KEYCLOAK_ENABLED:
        if required:
            raise KeycloakUnavailableError("La synchronisation avec Keycloak est désactivée.")
        return None
    if not account.keycloak_sub:
        if required:
            raise ApplicationError("Ce compte n'est pas encore lié à Keycloak.", code="account_not_linked")
        return None
    return account.keycloak_sub


def _not_self(account: BaseUser, actor: Any) -> None:
    if account.pk == getattr(actor, "pk", None):
        raise ApplicationError("Action impossible sur votre propre compte.", code="self_action")


def _keycloak_call(fn: Any, *args: Any) -> None:
    try:
        fn(*args)
    except KEYCLOAK_ERRORS as exc:
        raise KeycloakUnavailableError("Keycloak n'a pas pu exécuter l'action. Réessayez plus tard.") from exc


def _done(*, account: BaseUser, actor: Any, action: str, ip: str | None) -> BaseUser:
    audit_log(actor=actor, action=action, target=account, ip=ip)
    keycloak_directory_invalidate()  # l'état Keycloak vient de changer
    return account


@transaction.atomic
def account_lock(*, account: BaseUser, actor: Any, ip: str | None = None) -> BaseUser:
    """Désactive le compte dans Keycloak et ferme ses sessions ; l'API le refuse aussitôt (``is_active``)."""
    _not_self(account, actor)
    BaseUser.objects.filter(pk=account.pk).update(is_active=False)
    account.is_active = False
    keycloak_id = _keycloak_id(account, required=False)
    if keycloak_id:
        admin = keycloak_admin_client()
        _keycloak_call(admin.user_set_enabled, keycloak_id, False)
        _keycloak_call(admin.user_logout, keycloak_id)
    return _done(account=account, actor=actor, action="compte.verrouillage", ip=ip)


@transaction.atomic
def account_unlock(*, account: BaseUser, actor: Any, ip: str | None = None) -> BaseUser:
    """Réactive le compte et lève un éventuel blocage anti-force brute."""
    BaseUser.objects.filter(pk=account.pk).update(is_active=True)
    account.is_active = True
    keycloak_id = _keycloak_id(account, required=False)
    if keycloak_id:
        admin = keycloak_admin_client()
        _keycloak_call(admin.user_set_enabled, keycloak_id, True)
        _keycloak_call(admin.user_brute_force_reset, keycloak_id)
    return _done(account=account, actor=actor, action="compte.deverrouillage", ip=ip)


@transaction.atomic
def account_logout_sessions(*, account: BaseUser, actor: Any, ip: str | None = None) -> BaseUser:
    keycloak_id = _keycloak_id(account, required=True)
    _keycloak_call(keycloak_admin_client().user_logout, keycloak_id)
    return _done(account=account, actor=actor, action="compte.deconnexion_sessions", ip=ip)


@transaction.atomic
def account_require_mfa(*, account: BaseUser, actor: Any, ip: str | None = None) -> BaseUser:
    """La configuration d'un second facteur (TOTP) devient une action requise à la prochaine connexion."""
    keycloak_id = _keycloak_id(account, required=True)
    _keycloak_call(keycloak_admin_client().add_required_action, keycloak_id, REQUIRED_ACTION_TOTP)
    return _done(account=account, actor=actor, action="compte.mfa_exigee", ip=ip)
