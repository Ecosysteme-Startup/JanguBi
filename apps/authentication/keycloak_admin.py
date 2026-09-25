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
    pass


class KeycloakAdmin:
    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self.base = settings.KEYCLOAK_INTERNAL_URL
        self.realm = settings.KEYCLOAK_REALM
        self._client = client or httpx.Client(timeout=10.0)
        self._token: str | None = None
        self._token_expires_at = 0.0

    # --- transport ---------------------------------------------------------------------

    def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at - 30:
            return self._token
        if not settings.KEYCLOAK_ADMIN_CLIENT_SECRET:
            raise KeycloakAdminError("KEYCLOAK_ADMIN_CLIENT_SECRET n'est pas configuré.")
        response = self._client.post(
            f"{self.base}/realms/{self.realm}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": settings.KEYCLOAK_ADMIN_CLIENT_ID,
                "client_secret": settings.KEYCLOAK_ADMIN_CLIENT_SECRET,
            },
        )
        if response.status_code != 200:
            raise KeycloakAdminError(f"Jeton d'administration refusé ({response.status_code}).")
        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.monotonic() + float(payload.get("expires_in", 60))
        return self._token

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.base}/admin/realms/{self.realm}{path}"
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        response = self._client.request(method, url, headers=headers, **kwargs)
        if response.status_code >= 400 and response.status_code != 409:
            raise KeycloakAdminError(f"{method} {path} → {response.status_code}")
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

    def user_delete(self, user_id: str) -> None:
        """Suppression du compte Keycloak (EF-CONF-03). Absent (404) : déjà supprimé."""
        url = f"{self.base}/admin/realms/{self.realm}/users/{user_id}"
        response = self._client.request("DELETE", url, headers={"Authorization": f"Bearer {self._access_token()}"})
        if response.status_code >= 400 and response.status_code != 404:
            raise KeycloakAdminError(f"DELETE /users/{user_id} → {response.status_code}")

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
        "credentialData": json.dumps({"hashIterations": int(iterations), "algorithm": "pbkdf2-sha256", "additionalParameters": {}}),
        "secretData": json.dumps(
            {"value": hash_b64, "salt": base64.b64encode(salt.encode()).decode(), "additionalParameters": {}}
        ),
    }
