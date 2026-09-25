"""Lecture de l'état des comptes dans Keycloak pour l'administration plateforme.

Tout passe par le compte de service ``jangubi-admin-sync`` (``KeycloakAdmin``). Keycloak
injoignable ou désactivé (``KEYCLOAK_ENABLED``) : ces fonctions renvoient ``None`` et
l'appelant se rabat sur la base (mode dégradé) ; elles ne lèvent jamais.
"""

import datetime
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from django.conf import settings
from django.core.cache import cache

from apps.authentication.keycloak_admin import KeycloakAdmin, KeycloakAdminError

logger = logging.getLogger(__name__)

DIRECTORY_CACHE_KEY = "platform:accounts:kc-directory"
DIRECTORY_CACHE_SECONDS = 60
UNAVAILABLE_CACHE_SECONDS = 30
_UNAVAILABLE = "unavailable"

MFA_TOTP = "totp"
MFA_WEBAUTHN = "webauthn"
MFA_NONE = "facultative"
_WEBAUTHN_TYPES = frozenset({"webauthn", "webauthn-passwordless"})

KEYCLOAK_ERRORS = (KeycloakAdminError, httpx.HTTPError, ValueError, KeyError)


@dataclass(frozen=True)
class KeycloakAccount:
    enabled: bool
    email_verified: bool
    totp: bool


@dataclass(frozen=True)
class KeycloakDirectory:
    accounts: dict[str, KeycloakAccount]
    platform_admins: frozenset[str]


def keycloak_admin_client() -> KeycloakAdmin:
    return KeycloakAdmin()


def keycloak_directory() -> KeycloakDirectory | None:
    """Instantané de tous les comptes Keycloak (une minute en cache). ``None`` si indisponible
    (l'échec est mémorisé 30 s pour ne pas attendre Keycloak à chaque requête)."""
    cached = cache.get(DIRECTORY_CACHE_KEY)
    if cached == _UNAVAILABLE:
        return None
    if isinstance(cached, KeycloakDirectory):
        return cached
    if not settings.KEYCLOAK_ENABLED:
        return None
    try:
        admin = keycloak_admin_client()
        accounts = {
            str(u["id"]): KeycloakAccount(
                enabled=bool(u.get("enabled", True)),
                email_verified=bool(u.get("emailVerified", False)),
                totp=bool(u.get("totp", False)),
            )
            for u in admin.users_list()
        }
        platform_admins = frozenset(admin.role_members(settings.KEYCLOAK_PLATFORM_ADMIN_ROLE))
    except KEYCLOAK_ERRORS as exc:
        logger.warning("platform.accounts.keycloak_unavailable", extra={"error_type": type(exc).__name__})
        cache.set(DIRECTORY_CACHE_KEY, _UNAVAILABLE, UNAVAILABLE_CACHE_SECONDS)
        return None
    directory = KeycloakDirectory(accounts=accounts, platform_admins=platform_admins)
    cache.set(DIRECTORY_CACHE_KEY, directory, DIRECTORY_CACHE_SECONDS)
    return directory


def keycloak_directory_invalidate() -> None:
    cache.delete(DIRECTORY_CACHE_KEY)


def keycloak_mfa(keycloak_id: str) -> str | None:
    """Méthode MFA configurée (WebAuthn prime sur TOTP), ou ``None`` si Keycloak est injoignable."""
    if not settings.KEYCLOAK_ENABLED:
        return None
    try:
        types = {c.get("type") for c in keycloak_admin_client().user_credentials(keycloak_id)}
    except KEYCLOAK_ERRORS:
        return None
    if types & _WEBAUTHN_TYPES:
        return MFA_WEBAUTHN
    if "otp" in types:
        return MFA_TOTP
    return MFA_NONE


def keycloak_sessions(keycloak_id: str) -> list[dict[str, Any]] | None:
    """Sessions ouvertes ``[{id, client, ip, started_at}]``, ou ``None`` si Keycloak est injoignable."""
    if not settings.KEYCLOAK_ENABLED:
        return None
    try:
        raw = keycloak_admin_client().user_sessions(keycloak_id)
    except KEYCLOAK_ERRORS:
        return None
    sessions = []
    for s in raw:
        start = s.get("start")
        sessions.append(
            {
                "id": str(s.get("id", "")),
                "client": ", ".join(sorted(str(c) for c in (s.get("clients") or {}).values())),
                "ip": s.get("ipAddress") or None,
                "started_at": (
                    datetime.datetime.fromtimestamp(int(start) / 1000, tz=datetime.UTC) if start is not None else None
                ),
            }
        )
    return sessions
