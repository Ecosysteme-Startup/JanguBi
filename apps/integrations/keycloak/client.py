"""Client complet de l'API d'administration Keycloak, au-dessus du client minimal historique
(``apps.authentication.keycloak_admin.KeycloakAdmin``) : mêmes jetons, mêmes délais, mêmes
erreurs typées (``KeycloakUnavailableError``, ``KeycloakNotFoundError``, ``KeycloakConflictError``,
``KeycloakForbiddenError``, ``KeycloakBadRequestError``).

Rôles ``realm-management`` requis par le compte de service : ``view-users``, ``manage-users``,
``query-users``, ``view-realm`` (lecture des rôles), ``view-events`` (facultatif). Voir
``docs/ADMIN-KEYCLOAK.md``.
"""

from typing import Any

from django.conf import settings
from django.utils.module_loading import import_string

from apps.authentication.keycloak_admin import (
    KeycloakAdmin,
    KeycloakAdminError,
    KeycloakBadRequestError,
    KeycloakConflictError,
    KeycloakForbiddenError,
    KeycloakNotFoundError,
    KeycloakUnavailableError,
)

__all__ = [
    "KeycloakAdminClient",
    "KeycloakAdminError",
    "KeycloakBadRequestError",
    "KeycloakConflictError",
    "KeycloakForbiddenError",
    "KeycloakNotFoundError",
    "KeycloakUnavailableError",
    "REQUIRED_ACTIONS",
    "get_keycloak_admin",
]

# Actions requises proposées dans l'interface (``execute-actions-email``).
REQUIRED_ACTIONS = ("UPDATE_PASSWORD", "VERIFY_EMAIL", "CONFIGURE_TOTP", "UPDATE_PROFILE", "TERMS_AND_CONDITIONS")
# Seules les informations d'identification de second facteur peuvent être retirées par l'admin.
OTP_CREDENTIAL_TYPES = frozenset({"otp", "totp"})


class KeycloakAdminClient(KeycloakAdmin):
    """Toutes les opérations Keycloak utilisées par l'administration des comptes."""

    # --- utilisateurs ------------------------------------------------------------------

    def user_find(self, user_id: str) -> dict[str, Any] | None:
        try:
            return self.user_get(user_id)
        except KeycloakNotFoundError:
            return None

    def user_by_email(self, email: str) -> dict[str, Any] | None:
        users = self._request(
            "GET", "/users", params={"email": email, "exact": "true", "briefRepresentation": "false"}
        ).json()
        return users[0] if users else None

    def user_update(self, user_id: str, fields: dict[str, Any]) -> None:
        """Mise à jour partielle : Keycloak remplace la représentation, on repart donc de l'état courant."""
        current = self.user_get(user_id)
        current.update(fields)
        for key in ("access", "createdTimestamp", "totp", "disableableCredentialTypes", "notBefore"):
            current.pop(key, None)
        response = self._request("PUT", f"/users/{user_id}", json=current)
        if response.status_code == 409:
            raise KeycloakConflictError("Adresse e-mail déjà utilisée dans Keycloak.", status=409)

    def users_count(self) -> int:
        return int(self._request("GET", "/users/count").json())

    # --- actions ------------------------------------------------------------------------

    def execute_actions_email(
        self,
        user_id: str,
        actions: list[str],
        *,
        lifespan: int | None = None,
        client_id: str | None = None,
        redirect_uri: str | None = None,
    ) -> None:
        params: dict[str, Any] = {}
        if lifespan:
            params["lifespan"] = lifespan
        if client_id:
            params["client_id"] = client_id
        if redirect_uri:
            params["redirect_uri"] = redirect_uri
        self._request("PUT", f"/users/{user_id}/execute-actions-email", params=params, json=list(actions))

    def send_verify_email(self, user_id: str) -> None:
        self._request("PUT", f"/users/{user_id}/send-verify-email")

    def set_required_actions(self, user_id: str, actions: list[str]) -> None:
        self.user_update(user_id, {"requiredActions": sorted(set(actions))})

    # --- sessions -----------------------------------------------------------------------

    def session_delete(self, session_id: str) -> None:
        try:
            self._request("DELETE", f"/sessions/{session_id}")
        except KeycloakNotFoundError:
            return

    # --- informations d'identification --------------------------------------------------

    def credential_delete(self, user_id: str, credential_id: str) -> None:
        try:
            self._request("DELETE", f"/users/{user_id}/credentials/{credential_id}")
        except KeycloakNotFoundError:
            return

    def otp_reset(self, user_id: str) -> int:
        """Retire les seconds facteurs TOTP ; renvoie le nombre retiré. Le mot de passe reste."""
        removed = 0
        for credential in self.user_credentials(user_id):
            if credential.get("type") in OTP_CREDENTIAL_TYPES and credential.get("id"):
                self.credential_delete(user_id, str(credential["id"]))
                removed += 1
        return removed

    # --- force brute --------------------------------------------------------------------

    def brute_force_status(self, user_id: str) -> dict[str, Any]:
        return self._request("GET", f"/attack-detection/brute-force/users/{user_id}").json()

    # --- événements (Admin REST API ; « Save events » activé sur le realm) ------------

    def events(self, *, date_from: str, first: int = 0, max_results: int = 100) -> list[dict[str, Any]]:
        """Événements utilisateur (du plus récent au plus ancien). ``date_from`` : ``AAAA-MM-JJ``."""
        return self._request(
            "GET", "/events", params={"dateFrom": date_from, "first": first, "max": max_results}
        ).json()

    def admin_events(self, *, date_from: str, first: int = 0, max_results: int = 100) -> list[dict[str, Any]]:
        """Événements d'administration (du plus récent au plus ancien)."""
        return self._request(
            "GET", "/admin-events", params={"dateFrom": date_from, "first": first, "max": max_results}
        ).json()

    # --- groupes ------------------------------------------------------------------------

    def user_groups(self, user_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/users/{user_id}/groups").json()

    def realm_roles_list(self) -> list[dict[str, Any]]:
        return self._request("GET", "/roles").json()


def get_keycloak_admin() -> KeycloakAdminClient:
    """Client configuré : ``KEYCLOAK_ADMIN_BACKEND`` vaut ``http`` (défaut), ``fake`` (en mémoire)
    ou un chemin d'import vers une fabrique."""
    backend = getattr(settings, "KEYCLOAK_ADMIN_BACKEND", "http")
    if backend == "http":
        return KeycloakAdminClient()
    if backend == "fake":
        from apps.integrations.keycloak.fake import fake_keycloak

        return fake_keycloak()  # type: ignore[return-value]
    return import_string(backend)()
