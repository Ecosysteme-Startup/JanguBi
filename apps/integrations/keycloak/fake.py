"""Faux client d'administration Keycloak, en mémoire, pour les tests et le développement hors
ligne (``KEYCLOAK_ADMIN_BACKEND = "fake"``). Même interface et mêmes erreurs que le client
HTTP ; ``down = True`` simule un Keycloak injoignable. Aucun appel réseau."""

import copy
import time
import uuid
from typing import Any

from apps.authentication.keycloak_admin import (
    KeycloakConflictError,
    KeycloakNotFoundError,
    KeycloakUnavailableError,
)

_INSTANCE: "FakeKeycloakAdmin | None" = None


class FakeKeycloakAdmin:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.credentials: dict[str, list[dict[str, Any]]] = {}
        self.sessions: dict[str, list[dict[str, Any]]] = {}
        self.roles: dict[str, set[str]] = {"fidele": set(), "staff": set(), "platform_admin": set()}
        self.groups: dict[str, list[dict[str, Any]]] = {}
        self.brute_force: dict[str, dict[str, Any]] = {}
        self.emails: list[tuple[str, tuple[str, ...]]] = []
        self.calls: list[str] = []
        self.down = False
        self.fail_on: set[str] = set()
        self.user_events: list[dict[str, Any]] = []
        self.admin_event_log: list[dict[str, Any]] = []

    # --- outils de test --------------------------------------------------------------------

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.down or name in self.fail_on:
            raise KeycloakUnavailableError(f"{name} : Keycloak injoignable (faux client).")

    def _user(self, user_id: str) -> dict[str, Any]:
        if user_id not in self.users:
            raise KeycloakNotFoundError(f"utilisateur {user_id} absent", status=404)
        return self.users[user_id]

    def seed(
        self, *, email: str, user_id: str | None = None, first_name: str = "", last_name: str = "",
        enabled: bool = True, email_verified: bool = True, roles: tuple[str, ...] = ("fidele",),
        otp: bool = False,
    ) -> str:
        user_id = user_id or str(uuid.uuid4())
        self.users[user_id] = {
            "id": user_id,
            "username": email,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "enabled": enabled,
            "emailVerified": email_verified,
            "requiredActions": [],
            "attributes": {},
            "createdTimestamp": int(time.time() * 1000),
        }
        self.credentials[user_id] = [{"id": f"pwd-{user_id}", "type": "password"}]
        if otp:
            self.credentials[user_id].append({"id": f"otp-{user_id}", "type": "otp"})
        self.sessions[user_id] = []
        for role in roles:
            self.roles.setdefault(role, set()).add(user_id)
        return user_id

    # --- utilisateurs -----------------------------------------------------------------------

    def users_list(self, *, page_size: int = 500, limit: int = 20000) -> list[dict[str, Any]]:
        self._call("users_list")
        return [self._rep(u) for u in list(self.users.values())[:limit]]

    def _rep(self, user: dict[str, Any]) -> dict[str, Any]:
        rep = copy.deepcopy(user)
        rep["totp"] = any(c["type"] == "otp" for c in self.credentials.get(user["id"], []))
        return rep

    def users_count(self) -> int:
        self._call("users_count")
        return len(self.users)

    def user_get(self, user_id: str) -> dict[str, Any]:
        self._call("user_get")
        return self._rep(self._user(user_id))

    def user_find(self, user_id: str) -> dict[str, Any] | None:
        try:
            return self.user_get(user_id)
        except KeycloakNotFoundError:
            return None

    def user_by_email(self, email: str) -> dict[str, Any] | None:
        self._call("user_by_email")
        for user in self.users.values():
            if (user.get("email") or "").lower() == email.lower():
                return self._rep(user)
        return None

    def user_id_by_email(self, email: str) -> str | None:
        found = self.user_by_email(email)
        return found["id"] if found else None

    def user_create(self, representation: dict[str, Any]) -> tuple[str, bool]:
        self._call("user_create")
        existing = self.user_id_by_email(representation["email"])
        if existing:
            return existing, False
        user_id = self.seed(
            email=representation["email"],
            first_name=representation.get("firstName", ""),
            last_name=representation.get("lastName", ""),
            enabled=representation.get("enabled", True),
            email_verified=representation.get("emailVerified", False),
            roles=(),
        )
        self.users[user_id]["requiredActions"] = list(representation.get("requiredActions", []))
        self.users[user_id]["attributes"] = dict(representation.get("attributes", {}))
        return user_id, True

    def user_update(self, user_id: str, fields: dict[str, Any]) -> None:
        self._call("user_update")
        user = self._user(user_id)
        new_email = fields.get("email")
        if new_email:
            for other in self.users.values():
                if other["id"] != user_id and (other.get("email") or "").lower() == new_email.lower():
                    raise KeycloakConflictError("e-mail déjà pris", status=409)
        user.update(copy.deepcopy(fields))

    def user_set_enabled(self, user_id: str, enabled: bool) -> None:
        self.user_update(user_id, {"enabled": enabled})

    def user_delete(self, user_id: str) -> None:
        self._call("user_delete")
        self.users.pop(user_id, None)
        self.sessions.pop(user_id, None)
        self.credentials.pop(user_id, None)
        for members in self.roles.values():
            members.discard(user_id)

    # --- actions ------------------------------------------------------------------------------

    def add_required_action(self, user_id: str, action: str) -> None:
        user = self._user(user_id)
        if action not in user["requiredActions"]:
            self.user_update(user_id, {"requiredActions": sorted({*user["requiredActions"], action})})

    def remove_required_action(self, user_id: str, action: str) -> None:
        user = self._user(user_id)
        if action in user["requiredActions"]:
            self.user_update(user_id, {"requiredActions": sorted(set(user["requiredActions"]) - {action})})

    def set_required_actions(self, user_id: str, actions: list[str]) -> None:
        self.user_update(user_id, {"requiredActions": sorted(set(actions))})

    def execute_actions_email(self, user_id: str, actions: list[str], **kwargs: Any) -> None:
        self._call("execute_actions_email")
        self._user(user_id)
        self.emails.append((user_id, tuple(actions)))

    def send_verify_email(self, user_id: str) -> None:
        self._call("send_verify_email")
        self._user(user_id)
        self.emails.append((user_id, ("VERIFY_EMAIL",)))

    # --- sessions -----------------------------------------------------------------------------

    def user_sessions(self, user_id: str) -> list[dict[str, Any]]:
        self._call("user_sessions")
        self._user(user_id)
        return copy.deepcopy(self.sessions.get(user_id, []))

    def user_logout(self, user_id: str) -> None:
        self._call("user_logout")
        self._user(user_id)
        self.sessions[user_id] = []

    def session_delete(self, session_id: str) -> None:
        self._call("session_delete")
        for user_id, sessions in self.sessions.items():
            self.sessions[user_id] = [s for s in sessions if s.get("id") != session_id]

    # --- informations d'identification --------------------------------------------------------

    def user_credentials(self, user_id: str) -> list[dict[str, Any]]:
        self._call("user_credentials")
        self._user(user_id)
        return copy.deepcopy(self.credentials.get(user_id, []))

    def user_has_otp(self, user_id: str) -> bool:
        return any(c["type"] == "otp" for c in self.user_credentials(user_id))

    def credential_delete(self, user_id: str, credential_id: str) -> None:
        self._call("credential_delete")
        self.credentials[user_id] = [c for c in self.credentials.get(user_id, []) if c.get("id") != credential_id]

    def otp_reset(self, user_id: str) -> int:
        removed = [c for c in self.user_credentials(user_id) if c["type"] in ("otp", "totp")]
        for credential in removed:
            self.credential_delete(user_id, credential["id"])
        return len(removed)

    # --- force brute --------------------------------------------------------------------------

    def brute_force_status(self, user_id: str) -> dict[str, Any]:
        self._call("brute_force_status")
        return dict(self.brute_force.get(user_id, {"disabled": False, "numFailures": 0, "lastFailure": 0}))

    def user_brute_force_reset(self, user_id: str) -> None:
        self._call("user_brute_force_reset")
        self.brute_force.pop(user_id, None)

    # --- événements ---------------------------------------------------------------------------

    def _page(self, events: list[dict[str, Any]], date_from: str, first: int, max_results: int) -> list[dict[str, Any]]:
        import datetime

        start = datetime.datetime.fromisoformat(date_from).replace(tzinfo=datetime.UTC).timestamp() * 1000
        kept = sorted((e for e in events if e["time"] >= start), key=lambda e: e["time"], reverse=True)
        return copy.deepcopy(kept[first : first + max_results])

    def events(self, *, date_from: str, first: int = 0, max_results: int = 100) -> list[dict[str, Any]]:
        self._call("events")
        return self._page(self.user_events, date_from, first, max_results)

    def admin_events(self, *, date_from: str, first: int = 0, max_results: int = 100) -> list[dict[str, Any]]:
        self._call("admin_events")
        return self._page(self.admin_event_log, date_from, first, max_results)

    def record_user_event(self, event_type: str, user_id: str, *, at_ms: int | None = None) -> dict[str, Any]:
        event = {"id": str(uuid.uuid4()), "time": at_ms or int(time.time() * 1000), "type": event_type, "userId": user_id}
        self.user_events.append(event)
        return event

    def record_admin_event(
        self, operation: str, user_id: str, *, resource_type: str = "USER", at_ms: int | None = None
    ) -> dict[str, Any]:
        event = {
            "id": str(uuid.uuid4()),
            "time": at_ms or int(time.time() * 1000),
            "operationType": operation,
            "resourceType": resource_type,
            "resourcePath": f"users/{user_id}",
        }
        self.admin_event_log.append(event)
        return event

    # --- rôles et groupes ---------------------------------------------------------------------

    def user_realm_roles(self, user_id: str) -> set[str]:
        self._call("user_realm_roles")
        self._user(user_id)
        return {name for name, members in self.roles.items() if user_id in members}

    def add_realm_role(self, user_id: str, name: str) -> None:
        self._call("add_realm_role")
        self._user(user_id)
        self.roles.setdefault(name, set()).add(user_id)

    def remove_realm_role(self, user_id: str, name: str) -> None:
        self._call("remove_realm_role")
        self.roles.setdefault(name, set()).discard(user_id)

    def role_members(self, name: str) -> list[str]:
        self._call("role_members")
        return sorted(self.roles.get(name, set()))

    def realm_roles_list(self) -> list[dict[str, Any]]:
        self._call("realm_roles_list")
        return [{"name": name} for name in sorted(self.roles)]

    def user_groups(self, user_id: str) -> list[dict[str, Any]]:
        self._call("user_groups")
        return copy.deepcopy(self.groups.get(user_id, []))


def fake_keycloak() -> FakeKeycloakAdmin:
    """Instance partagée du processus (les tests la remettent à zéro par ``reset()``)."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = FakeKeycloakAdmin()
    return _INSTANCE
