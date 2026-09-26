"""Rattachement Keycloak ↔ personne AVANT la transaction de la requête.

Avec ``ATOMIC_REQUESTS``, la vue s'exécute dans une transaction que DRF annule dès qu'une
exception est traitée (401/403). Le premier appel d'un responsable (``/me/capacites/``,
refusé en ``mfa_required`` faute d'OTP) annulait donc aussi le rattachement de son compte :
le rôle ``staff`` n'était jamais accordé, Keycloak ne demandait jamais l'OTP, et le compte
restait bloqué hors de son espace. Un middleware s'exécute hors de cette transaction : ce
qu'il écrit est validé tout de suite.
"""

import logging
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse

from apps.authentication.keycloak import KeycloakIdentity, KeycloakTokenError, person_from_identity, token_validate

logger = logging.getLogger(__name__)

# Un responsable dont le jeton n'a pas encore le rôle staff : on ne resynchronise qu'une fois
# par période (appel à l'API d'administration Keycloak), le temps qu'il se reconnecte.
STAFF_SYNC_COOLDOWN_S = 600


def _bearer(request: HttpRequest) -> str | None:
    header = request.META.get("HTTP_AUTHORIZATION", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def _staff_sync_if_needed(person: Any, identity: KeycloakIdentity) -> None:
    from apps.authentication.services_keycloak import keycloak_staff_role_sync
    from apps.hierarchy.authz import active_assignments

    if settings.KEYCLOAK_STAFF_ROLE in identity.realm_roles:
        return
    key = f"authz:staff-sync:{person.pk}"
    if cache.get(key) or not active_assignments(user=person).exists():
        return
    cache.set(key, True, STAFF_SYNC_COOLDOWN_S)
    try:
        keycloak_staff_role_sync(person=person)
    except Exception:  # Keycloak injoignable : la réconciliation nocturne rattrapera.
        logger.warning("keycloak.staff_sync_failed", exc_info=True)


class KeycloakProvisioningMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        token = _bearer(request)
        if token and settings.KEYCLOAK_ENABLED:
            self._provision(request, token)
        return self.get_response(request)

    @staticmethod
    def _provision(request: HttpRequest, token: str) -> None:
        try:
            identity = token_validate(token)
        except KeycloakTokenError:
            return  # l'authentification DRF répondra 401 avec le motif
        request._keycloak_identity = (token, identity)  # type: ignore[attr-defined]
        if get_user_model().objects.filter(keycloak_sub=identity.sub).exists() and (
            settings.KEYCLOAK_STAFF_ROLE in identity.realm_roles
        ):
            return
        try:
            person = person_from_identity(identity)  # validé immédiatement (hors transaction de vue)
        except KeycloakTokenError:
            return
        _staff_sync_if_needed(person, identity)
