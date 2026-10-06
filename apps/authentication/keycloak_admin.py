"""Client minimal de l'API d'administration Keycloak (compte de service ``jangubi-admin-sync``).

Utilisé pour la synchronisation du rôle ``staff`` (EF-AUTH-04) et la migration des
comptes (EF-AUTH-06). Aucune donnée ecclésiale n'est envoyée à Keycloak.
"""

import base64
import json
import time
from typing import Any

import httpx
from django.conf import settings


class KeycloakAdminError(Exception):
    """Erreur de l'API d'administration Keycloak. ``status`` : code HTTP (0 = réseau)."""

    def __init__(self, message: str = "", *, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class KeycloakUnavailableError(KeycloakAdminError):
    """Keycloak injoignable, lent (délai dépassé) ou en erreur 5xx : réessayer plus tard."""


class KeycloakNotFoundError(KeycloakAdminError):
    """Ressource absente (404)."""


class KeycloakConflictError(KeycloakAdminError):
    """Conflit (409) : e-mail ou identifiant déjà pris."""


class KeycloakForbiddenError(KeycloakAdminError):
    """Le compte de service n'a pas le rôle ``realm-management`` requis (401/403)."""


class KeycloakBadRequestError(KeycloakAdminError):
    """Requête refusée par Keycloak (400), p. ex. action requise inconnue."""


def keycloak_error_for(status: int, message: str) -> KeycloakAdminError:
    if status == 404:
        return KeycloakNotFoundError(message, status=status)
    if status == 409:
        return KeycloakConflictError(message, status=status)
    if status in (401, 403):
        return KeycloakForbiddenError(message, status=status)
    if status >= 500 or status == 0:
        return KeycloakUnavailableError(message, status=status)
    return KeycloakBadRequestError(message, status=status)


def _default_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        float(getattr(settings, "KEYCLOAK_ADMIN_TIMEOUT_SECONDS", 10.0)),
        connect=float(getattr(settings, "KEYCLOAK_ADMIN_CONNECT_TIMEOUT_SECONDS", 3.0)),
    )


class KeycloakAdmin:
    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self.base = settings.KEYCLOAK_INTERNAL_URL
        self.realm = settings.KEYCLOAK_REALM
        self._client = client or httpx.Client(timeout=_default_timeout())
        self._token: str | None = None
        self._token_expires_at = 0.0

    # --- transport ---------------------------------------------------------------------

    def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at - 30:
            return self._token
        if not settings.KEYCLOAK_ADMIN_CLIENT_SECRET:
            raise KeycloakAdminError("KEYCLOAK_ADMIN_CLIENT_SECRET n'est pas configuré.")
        try:
            response = self._client.post(
                f"{self.base}/realms/{self.realm}/protocol/openid-connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.KEYCLOAK_ADMIN_CLIENT_ID,
                    "client_secret": settings.KEYCLOAK_ADMIN_CLIENT_SECRET,
                },
            )
        except httpx.HTTPError as exc:
            raise KeycloakUnavailableError(f"Keycloak injoignable ({type(exc).__name__}).") from exc
        if response.status_code != 200:
            raise keycloak_error_for(
                response.status_code if response.status_code >= 500 else 403,
                f"Jeton d'administration refusé ({response.status_code}).",
            )
        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.monotonic() + float(payload.get("expires_in", 60))
        return self._token

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.base}/admin/realms/{self.realm}{path}"
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        try:
            response = self._client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise KeycloakUnavailableError(f"{method} {path} : Keycloak injoignable ({type(exc).__name__}).") from exc
        if response.status_code >= 400 and response.status_code != 409:
            raise keycloak_error_for(response.status_code, f"{method} {path} → {response.status_code}")
        return response

    # --- rôles -------------------------------------------------------------------------

    def realm_role(self, name: str) -> dict[str, Any]:
        return self._request("GET", f"/roles/{name}").json()

    def user_realm_roles(self, user_id: str) -> set[str]:
        return {r["name"] for r in self._request("GET", f"/users/{user_id}/role-mappings/realm").json()}

    def add_realm_role(self, user_id: str, name: str) -> None:
        self._request("POST", f"/users/{user_id}/role-mappings/realm", json=[self.realm_role(name)])

    def remove_realm_role(self, user_id: str, name: str) -> None:
        self._request("DELETE", f"/users/{user_id}/role-mappings/realm", json=[self.realm_role(name)])

    def role_members(self, name: str) -> list[str]:
        ids: list[str] = []
        first = 0
        while True:
            page = self._request("GET", f"/roles/{name}/users", params={"first": first, "max": 100}).json()
            ids += [u["id"] for u in page]
            if len(page) < 100:
                return ids
            first += 100

    # --- utilisateurs ------------------------------------------------------------------

    def user_has_otp(self, user_id: str) -> bool:
        return any(c.get("type") == "otp" for c in self._request("GET", f"/users/{user_id}/credentials").json())

    def add_required_action(self, user_id: str, action: str) -> None:
        user = self._request("GET", f"/users/{user_id}").json()
        actions = set(user.get("requiredActions", []))
        if action not in actions:
            self._request("PUT", f"/users/{user_id}", json={"requiredActions": sorted(actions | {action})})

    def remove_required_action(self, user_id: str, action: str) -> None:
        user = self._request("GET", f"/users/{user_id}").json()
        actions = set(user.get("requiredActions", []))
        if action in actions:
            self._request("PUT", f"/users/{user_id}", json={"requiredActions": sorted(actions - {action})})

    # --- comptes plateforme (plateforme.admin) -------------------------------------------

    def users_list(self, *, page_size: int = 500, limit: int = 20000) -> list[dict[str, Any]]:
        """Représentations complètes (``enabled``, ``emailVerified``, ``totp``) de tous les comptes."""
        users: list[dict[str, Any]] = []
        first = 0
        while first < limit:
            page = self._request(
                "GET", "/users", params={"first": first, "max": page_size, "briefRepresentation": "false"}
            ).json()
            users += page
            if len(page) < page_size:
                break
            first += page_size
        return users

    def user_get(self, user_id: str) -> dict[str, Any]:
        return self._request("GET", f"/users/{user_id}").json()

    def user_credentials(self, user_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/users/{user_id}/credentials").json()

    def user_sessions(self, user_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/users/{user_id}/sessions").json()

    def user_set_enabled(self, user_id: str, enabled: bool) -> None:
        self._request("PUT", f"/users/{user_id}", json={"enabled": enabled})

    def user_logout(self, user_id: str) -> None:
        """Ferme toutes les sessions (et révoque les jetons de rafraîchissement) du compte."""
        self._request("POST", f"/users/{user_id}/logout")

    def user_brute_force_reset(self, user_id: str) -> None:
        self._request("DELETE", f"/attack-detection/brute-force/users/{user_id}")

    def user_delete(self, user_id: str) -> None:
        """Suppression du compte Keycloak (EF-CONF-03). Absent (404) : déjà supprimé."""
        try:
            self._request("DELETE", f"/users/{user_id}")
        except KeycloakNotFoundError:
            return

    def user_id_by_email(self, email: str) -> str | None:
        users = self._request("GET", "/users", params={"email": email, "exact": "true"}).json()
        return users[0]["id"] if users else None

    def user_create(self, representation: dict[str, Any]) -> tuple[str, bool]:
        """Crée l'utilisateur ; renvoie (id, créé). Un e-mail déjà présent n'est pas une erreur."""
        response = self._request("POST", "/users", json=representation)
        if response.status_code == 409:
            existing = self.user_id_by_email(representation["email"])
            if existing is None:
                raise KeycloakAdminError(f"Conflit Keycloak pour {representation['email']}.")
            return existing, False
        return response.headers["Location"].rstrip("/").rsplit("/", 1)[-1], True


# --- Conversion des mots de passe Django (EF-AUTH-06) ------------------------------------


def django_hash_to_keycloak_credential(encoded: str) -> dict[str, Any] | None:
    """``pbkdf2_sha256$<itérations>$<sel>$<hash b64>`` → credential Keycloak ``pbkdf2-sha256``.

    Keycloak attend le sel en base64 des octets ; Django stocke le sel en clair. La clé
    dérivée (32 octets, base64) est identique des deux côtés. ``None`` si non convertible.
    """
    try:
        algorithm, iterations, salt, hash_b64 = encoded.split("$", 3)
    except ValueError:
        return None
    if algorithm != "pbkdf2_sha256" or not iterations.isdigit() or not salt or not hash_b64:
        return None
    return {
        "type": "password",
        "credentialData": json.dumps(
            {"hashIterations": int(iterations), "algorithm": "pbkdf2-sha256", "additionalParameters": {}}
        ),
        "secretData": json.dumps(
            {"value": hash_b64, "salt": base64.b64encode(salt.encode()).decode(), "additionalParameters": {}}
        ),
    }
