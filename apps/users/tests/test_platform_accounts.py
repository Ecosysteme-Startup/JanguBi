"""Comptes plateforme : GET/POST /api/v1/platform/accounts/ (plateforme.admin, MFA exigée).

Keycloak n'est jamais appelé pour de vrai : l'API d'administration est simulée par un
``httpx.MockTransport`` branché sur le vrai client ``KeycloakAdmin``.
"""

import dataclasses
import datetime
import json
import re
from typing import Any

import httpx
import pytest
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.keycloak_admin import KeycloakAdmin
from apps.hierarchy.models import AuditEvent
from apps.hierarchy.tests.factories import Tree, nominate, person, priest
from apps.users.models import BaseUser, Profile
from apps.users.tests.factories import platform_identity

pytestmark = pytest.mark.django_db
URL = "/api/v1/platform/accounts/"
SECRET = "contenu de message 7f3a jamais exposé"


class FakeKeycloak:
    """API d'administration Keycloak en mémoire (sous-ensemble utilisé par l'application)."""

    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.credentials: dict[str, list[dict[str, Any]]] = {}
        self.sessions: dict[str, list[dict[str, Any]]] = {}
        self.platform_admins: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self.down = False

    def add(self, user: BaseUser, *, enabled=True, verified=True, totp=False, credentials=(), sessions=()) -> None:
        sub = f"kc-{user.pk}"
        BaseUser.objects.filter(pk=user.pk).update(keycloak_sub=sub)
        user.keycloak_sub = sub
        self.users[sub] = {"id": sub, "enabled": enabled, "emailVerified": verified, "totp": totp, "requiredActions": []}
        self.credentials[sub] = [{"type": t} for t in credentials]
        self.sessions[sub] = list(sessions)

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("Keycloak injoignable", request=request)
        path, method = request.url.path, request.method
        self.calls.append((method, path))
        if path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        path = path.split("/admin/realms/jangubi", 1)[1]
        if path == "/users" and method == "GET":
            first, size = int(request.url.params["first"]), int(request.url.params["max"])
            return httpx.Response(200, json=list(self.users.values())[first : first + size])
        if path == "/roles/platform_admin/users":
            return httpx.Response(200, json=[{"id": i} for i in self.platform_admins])
        if match := re.fullmatch(r"/attack-detection/brute-force/users/([^/]+)", path):
            return httpx.Response(204)
        match = re.fullmatch(r"/users/([^/]+)(/[a-z-]+)?", path)
        assert match, path
        sub, action = match.group(1), match.group(2)
        if sub not in self.users:
            return httpx.Response(404)
        if action is None and method == "GET":
            return httpx.Response(200, json=self.users[sub])
        if action is None and method == "PUT":
            self.users[sub].update(json.loads(request.content))
            return httpx.Response(204)
        if action == "/credentials":
            return httpx.Response(200, json=self.credentials[sub])
        if action == "/sessions":
            return httpx.Response(200, json=self.sessions[sub])
        if action == "/logout":
            self.sessions[sub] = []
            return httpx.Response(204)
        raise AssertionError(f"Appel Keycloak inattendu : {method} {path}")


@pytest.fixture
def keycloak(monkeypatch, settings) -> FakeKeycloak:
    settings.KEYCLOAK_ENABLED = True
    settings.KEYCLOAK_ADMIN_CLIENT_SECRET = "secret-de-test"
    fake = FakeKeycloak()
    client = httpx.Client(transport=httpx.MockTransport(fake.handler))
    monkeypatch.setattr("apps.users.keycloak_accounts.KeycloakAdmin", lambda: KeycloakAdmin(client=client))
    return fake


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def named(user: BaseUser, first: str, last: str) -> BaseUser:
    Profile.objects.update_or_create(user=user, defaults={"first_name": first, "last_name": last})
    return user


@pytest.fixture
def world(keycloak):
    tree = Tree()
    today = timezone.localdate()
    tree.admin = platform_identity(named(person("admin@numerisen.sn"), "Awa", "Admin"))
    keycloak.add(tree.admin, totp=True)
    keycloak.platform_admins.append(tree.admin.keycloak_sub)

    tree.cure = named(priest("cure@sd.sn"), "Jean", "Diouf")
    nominate(tree.cure, "cure", tree.saint_dominique)
    keycloak.add(
        tree.cure,
        totp=True,
        credentials=("password", "otp"),
        sessions=[{"id": "s1", "ipAddress": "10.0.0.1", "start": 1_790_000_000_000, "clients": {"c": "jangubi-web"}}],
    )

    tree.fidele = named(person("fidele@test.sn"), "Moussa", "Ndiaye")
    tree.fidele.paroisse_suivie = tree.sainte_therese
    tree.fidele.save(update_fields=["paroisse_suivie"])
    keycloak.add(tree.fidele)

    tree.locked = person("verrouille@test.sn")
    keycloak.add(tree.locked, enabled=False)
    tree.unconfirmed = person("nouveau@test.sn")
    keycloak.add(tree.unconfirmed, verified=False)
    tree.unlinked = person("non-lie@test.sn", is_verified=False)  # jamais connecté via Keycloak

    for user, days in ((tree.cure, 0), (tree.fidele, 1), (tree.admin, 2), (tree.locked, 5)):
        BaseUser.objects.filter(pk=user.pk).update(last_seen_on=today - datetime.timedelta(days=days))
    return tree


def items(response) -> dict[str, dict[str, Any]]:
    assert response.status_code == 200, response.content
    return {item["email"]: item for item in response.json()["results"]}


# --- Permissions ---------------------------------------------------------------------------


def test_anonymous_is_rejected(world):
    assert APIClient().get(URL).status_code == 401
    assert APIClient().post(f"{URL}{world.fidele.pk}/lock/").status_code == 401


def test_staff_and_fideles_are_forbidden(world):
    for user in (world.cure, world.fidele):
        assert client_for(user).get(URL).status_code == 403
        assert client_for(user).get(f"{URL}{world.fidele.pk}/").status_code == 403
        assert client_for(user).post(f"{URL}{world.fidele.pk}/lock/").status_code == 403


def test_platform_admin_without_mfa_is_forbidden(world):
    admin = person("admin2@numerisen.sn")
    platform_identity(admin)
    admin.keycloak_identity = dataclasses.replace(admin.keycloak_identity, amr=frozenset({"pwd"}), acr="1")
    response = client_for(admin).get(URL)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "mfa_required"


# --- Liste ---------------------------------------------------------------------------------


def test_list_items_and_order(world):
    response = client_for(world.admin).get(URL, {"limit": 50})
    body = response.json()
    assert set(body) == {"limit", "offset", "count", "next", "previous", "results"}
    assert [i["email"] for i in body["results"]][:4] == [
        "cure@sd.sn",
        "fidele@test.sn",
        "admin@numerisen.sn",
        "verrouille@test.sn",
    ]
    rows = items(response)
    assert rows["cure@sd.sn"] == {
        "id": str(world.cure.pk),
        "email": "cure@sd.sn",
        "full_name": "Jean Diouf",
        "realm_role": "staff",
        "mfa": "totp",
        "last_login": rows["cure@sd.sn"]["last_login"],
        "status": "actif",
        "node_label": "Saint-Dominique",
    }
    assert rows["cure@sd.sn"]["last_login"] is not None
    assert rows["admin@numerisen.sn"]["realm_role"] == "platform_admin"
    assert rows["fidele@test.sn"]["realm_role"] == "fidele"
    assert rows["fidele@test.sn"]["node_label"] == "Sainte-Thérèse"
    assert rows["fidele@test.sn"]["mfa"] == "facultative"
    assert rows["verrouille@test.sn"]["status"] == "verrouille"
    assert rows["nouveau@test.sn"]["status"] == "a_confirmer"
    assert rows["non-lie@test.sn"]["status"] == "a_confirmer"
    assert rows["non-lie@test.sn"]["last_login"] is None
    assert rows["non-lie@test.sn"]["node_label"] is None


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"role": "platform_admin"}, {"admin@numerisen.sn"}),
        ({"role": "staff"}, {"cure@sd.sn"}),
        ({"role": "fidele", "q": "test.sn"}, {"fidele@test.sn", "verrouille@test.sn", "nouveau@test.sn", "non-lie@test.sn"}),
        ({"mfa": "active"}, {"admin@numerisen.sn", "cure@sd.sn"}),
        ({"status": "verrouille"}, {"verrouille@test.sn"}),
        ({"status": "a_confirmer"}, {"nouveau@test.sn", "non-lie@test.sn"}),
        ({"q": "diouf"}, {"cure@sd.sn"}),
        ({"q": "diouf", "status": "actif", "mfa": "facultative"}, set()),
    ],
)
def test_list_filters(world, params, expected):
    assert set(items(client_for(world.admin).get(URL, {"limit": 50, **params}))) == expected


def test_list_rejects_unknown_filter_values(world):
    response = client_for(world.admin).get(URL, {"role": "super_admin"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_list_is_degraded_when_keycloak_is_down(world, keycloak):
    keycloak.down = True
    BaseUser.objects.filter(pk=world.cure.pk).update(last_mfa_on=timezone.localdate())

    rows = items(client_for(world.admin).get(URL, {"limit": 50}))

    assert rows["cure@sd.sn"]["mfa"] == "totp"  # dernière connexion MFA connue en base
    assert rows["fidele@test.sn"]["mfa"] == "facultative"
    assert rows["verrouille@test.sn"]["status"] == "actif"  # verrou Keycloak inconnu
    assert rows["non-lie@test.sn"]["status"] == "a_confirmer"
    assert rows["admin@numerisen.sn"]["realm_role"] == "fidele"  # rôle de realm inconnu
    assert rows["cure@sd.sn"]["realm_role"] == "staff"


def test_list_never_exposes_message_content(world):
    from apps.messaging.tests.factories import ConversationFactory, MessageFactory

    conversation = ConversationFactory(participant_a=world.fidele, participant_b=world.cure)
    MessageFactory(conversation=conversation, sender=world.fidele, content=SECRET)
    response = client_for(world.admin).get(URL)
    detail = client_for(world.admin).get(f"{URL}{world.fidele.pk}/")
    assert SECRET not in response.content.decode() and SECRET not in detail.content.decode()


# --- Fiche ---------------------------------------------------------------------------------


def test_detail(world):
    response = client_for(world.admin).get(f"{URL}{world.cure.pk}/")
    assert response.status_code == 200
    body = response.json()
    assert body["keycloak_id"] == world.cure.keycloak_sub
    assert body["email_verified"] is True
    assert body["realm_role"] == "staff" and body["mfa"] == "totp"
    assert body["offices"] == [
        {
            "office_label": body["offices"][0]["office_label"],
            "node_name": "Saint-Dominique",
            "start_date": "2020-01-01",
            "capabilities": body["offices"][0]["capabilities"],
        }
    ]
    assert "actes.traiter" in body["offices"][0]["capabilities"]
    assert body["sessions"] == [
        {"id": "s1", "client": "jangubi-web", "ip": "10.0.0.1", "started_at": "2026-09-21T14:13:20Z"}
    ]


def test_detail_webauthn_takes_precedence(world, keycloak):
    keycloak.credentials[world.fidele.keycloak_sub] = [{"type": "otp"}, {"type": "webauthn"}]
    assert client_for(world.admin).get(f"{URL}{world.fidele.pk}/").json()["mfa"] == "webauthn"


def test_detail_unlinked_and_unknown(world):
    body = client_for(world.admin).get(f"{URL}{world.unlinked.pk}/").json()
    assert body["keycloak_id"] is None and body["sessions"] == [] and body["email_verified"] is False
    missing = client_for(world.admin).get(f"{URL}00000000-0000-0000-0000-000000000000/")
    assert missing.status_code == 404


def test_detail_is_degraded_when_keycloak_is_down(world, keycloak):
    keycloak.down = True
    response = client_for(world.admin).get(f"{URL}{world.cure.pk}/")
    assert response.status_code == 200
    assert response.json()["sessions"] == []
    assert response.json()["offices"][0]["node_name"] == "Saint-Dominique"


# --- Actions -------------------------------------------------------------------------------


def audit_actions(user) -> list[str]:
    return list(AuditEvent.objects.filter(target_id=str(user.pk)).order_by("at", "pk").values_list("action", flat=True))


def test_lock_and_unlock(world, keycloak):
    sub = world.fidele.keycloak_sub
    keycloak.sessions[sub] = [{"id": "s9", "ipAddress": "10.0.0.9", "start": 1_790_000_000_000, "clients": {}}]

    locked = client_for(world.admin).post(f"{URL}{world.fidele.pk}/lock/")
    assert locked.status_code == 200
    assert locked.json()["status"] == "verrouille" and locked.json()["sessions"] == []
    assert keycloak.users[sub]["enabled"] is False
    assert BaseUser.objects.get(pk=world.fidele.pk).is_active is False

    unlocked = client_for(world.admin).post(f"{URL}{world.fidele.pk}/unlock/")
    assert unlocked.status_code == 200 and unlocked.json()["status"] == "actif"
    assert keycloak.users[sub]["enabled"] is True
    assert ("DELETE", f"/admin/realms/jangubi/attack-detection/brute-force/users/{sub}") in keycloak.calls
    assert audit_actions(world.fidele) == ["compte.verrouillage", "compte.deverrouillage"]
    event = AuditEvent.objects.get(action="compte.verrouillage")
    assert event.actor_id == world.admin.pk and event.metadata == {}


def test_logout_sessions(world, keycloak):
    response = client_for(world.admin).post(f"{URL}{world.cure.pk}/logout-sessions/")
    assert response.status_code == 200 and response.json()["sessions"] == []
    assert ("POST", f"/admin/realms/jangubi/users/{world.cure.keycloak_sub}/logout") in keycloak.calls
    assert audit_actions(world.cure) == ["compte.deconnexion_sessions"]


def test_require_mfa(world, keycloak):
    response = client_for(world.admin).post(f"{URL}{world.fidele.pk}/require-mfa/")
    assert response.status_code == 200
    assert keycloak.users[world.fidele.keycloak_sub]["requiredActions"] == ["CONFIGURE_TOTP"]
    assert audit_actions(world.fidele) == ["compte.mfa_exigee"]


@pytest.mark.parametrize("action", ["lock", "unlock", "logout-sessions", "require-mfa"])
def test_actions_fail_cleanly_when_keycloak_is_down(world, keycloak, action):
    keycloak.down = True
    response = client_for(world.admin).post(f"{URL}{world.fidele.pk}/{action}/")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "keycloak_unavailable"
    assert BaseUser.objects.get(pk=world.fidele.pk).is_active is True
    assert audit_actions(world.fidele) == []


def test_cannot_lock_own_account(world):
    response = client_for(world.admin).post(f"{URL}{world.admin.pk}/lock/")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "self_action"


def test_unlinked_account(world, keycloak):
    assert client_for(world.admin).post(f"{URL}{world.unlinked.pk}/logout-sessions/").status_code == 400
    locked = client_for(world.admin).post(f"{URL}{world.unlinked.pk}/lock/")
    assert locked.status_code == 200 and locked.json()["status"] == "verrouille"
    assert audit_actions(world.unlinked) == ["compte.verrouillage"]


@override_settings(KEYCLOAK_ENABLED=False)
def test_keycloak_sync_disabled(world):
    rows = items(client_for(world.admin).get(URL, {"limit": 50}))
    assert rows["verrouille@test.sn"]["status"] == "actif"
    response = client_for(world.admin).post(f"{URL}{world.fidele.pk}/require-mfa/")
    assert response.status_code == 503
