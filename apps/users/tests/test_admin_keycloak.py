"""Administration des comptes synchronisée avec Keycloak (docs/ADMIN-KEYCLOAK.md).

Keycloak est simulé par le faux client en mémoire (``KEYCLOAK_ADMIN_BACKEND = "fake"``) ; le
client HTTP réel est testé contre un ``httpx.MockTransport``.
"""

import csv
import hashlib
import hmac
import io
import json

import httpx
import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.authentication.keycloak_admin import (
    KeycloakConflictError,
    KeycloakForbiddenError,
    KeycloakNotFoundError,
    KeycloakUnavailableError,
)
from apps.hierarchy.models import AuditEvent
from apps.hierarchy.tests.factories import Tree, nominate, person, priest
from apps.integrations.keycloak.client import KeycloakAdminClient
from apps.integrations.keycloak.fake import fake_keycloak
from apps.users.models import BaseUser, KeycloakEvent, KeycloakSyncRun, Profile
from apps.users.tests.factories import platform_identity

pytestmark = pytest.mark.django_db
BASE = "/api/v1/admin/"
ACCOUNTS = f"{BASE}accounts/"


@pytest.fixture(autouse=True)
def _on_commit(monkeypatch):
    """Les tests tournent dans une transaction jamais validée : les rappels ``on_commit``
    (tâches différées, exécutées sur-le-champ par Celery en mode eager) sont lancés aussitôt."""
    monkeypatch.setattr("django.db.transaction.on_commit", lambda func, using=None, robust=False: func())


@pytest.fixture
def kc(settings):
    settings.KEYCLOAK_ENABLED = True
    settings.KEYCLOAK_ADMIN_BACKEND = "fake"
    fake = fake_keycloak()
    fake.reset()
    return fake


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def linked(kc, user, *, roles=("fidele",), otp=False) -> BaseUser:
    """Lie un compte de l'application à un compte du faux Keycloak."""
    profile = Profile.objects.filter(user=user).first()
    sub = kc.seed(
        email=user.email,
        first_name=profile.first_name if profile else "",
        last_name=profile.last_name if profile else "",
        enabled=user.is_active,
        email_verified=user.is_verified,
        roles=roles,
        otp=otp,
    )
    BaseUser.objects.filter(pk=user.pk).update(keycloak_sub=sub, keycloak_platform_admin="platform_admin" in roles)
    user.keycloak_sub = sub
    user.keycloak_platform_admin = "platform_admin" in roles
    return user


@pytest.fixture
def world(kc):
    tree = Tree()
    tree.admin = linked(kc, platform_identity(person("admin@numerisen.sn")), roles=("platform_admin",), otp=True)
    tree.admin2 = linked(kc, person("admin2@numerisen.sn"), roles=("platform_admin",))
    tree.eveque = linked(kc, person("eveque@dakar.sn", ordre="eveque"))
    nominate(tree.eveque, "eveque_diocesain", tree.dakar)
    tree.chancelier = linked(kc, person("chancelier@dakar.sn"))
    nominate(tree.chancelier, "chancelier", tree.dakar)
    tree.cure = linked(kc, priest("cure@sd.sn"))
    nominate(tree.cure, "cure", tree.saint_dominique)
    tree.vicaire = linked(kc, priest("vicaire@sd.sn"))
    nominate(tree.vicaire, "vicaire_paroissial", tree.saint_dominique)
    tree.cure_thies = linked(kc, priest("cure@thies.sn"))
    nominate(tree.cure_thies, "cure", tree.thies_parish)
    tree.fidele = linked(kc, person("fidele@test.sn"))
    return tree


def create(actor, node, email="secretaire@sd.sn", **extra):
    payload = {"email": email, "first_name": "Cécile", "last_name": "Coly", "node_id": str(node.pk), **extra}
    return client_for(actor).post(ACCOUNTS, payload, format="json")


# --- Client HTTP : délais et erreurs typées ------------------------------------------------


def _http_client(handler) -> KeycloakAdminClient:
    return KeycloakAdminClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize(
    ("status", "error"),
    [(404, KeycloakNotFoundError), (403, KeycloakForbiddenError), (503, KeycloakUnavailableError)],
)
def test_http_client_maps_errors(settings, status, error):
    settings.KEYCLOAK_ADMIN_CLIENT_SECRET = "s"

    def handler(request):
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        return httpx.Response(status)

    with pytest.raises(error):
        _http_client(handler).user_get("abc")


def test_http_client_timeout_is_unavailable(settings):
    settings.KEYCLOAK_ADMIN_CLIENT_SECRET = "s"

    def handler(request):
        raise httpx.ReadTimeout("lent", request=request)

    with pytest.raises(KeycloakUnavailableError):
        _http_client(handler).user_get("abc")


def test_http_client_update_merges_and_detects_conflict(settings):
    settings.KEYCLOAK_ADMIN_CLIENT_SECRET = "s"
    sent = {}

    def handler(request):
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        if request.method == "GET":
            return httpx.Response(200, json={"id": "u1", "email": "a@b.sn", "firstName": "A", "totp": False})
        sent.update(json.loads(request.content))
        return httpx.Response(409)

    with pytest.raises(KeycloakConflictError):
        _http_client(handler).user_update("u1", {"lastName": "B"})
    assert sent == {"id": "u1", "email": "a@b.sn", "firstName": "A", "lastName": "B"}


def test_http_client_otp_reset_only_removes_second_factor(settings):
    settings.KEYCLOAK_ADMIN_CLIENT_SECRET = "s"
    deleted = []

    def handler(request):
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 300})
        if request.method == "GET":
            return httpx.Response(200, json=[{"id": "p", "type": "password"}, {"id": "o", "type": "otp"}])
        deleted.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(204)

    assert _http_client(handler).otp_reset("u1") == 1
    assert deleted == ["o"]


# --- Création (application → Keycloak) ------------------------------------------------------


def test_platform_creates_account_in_both_systems(world, kc):
    response = create(world.admin, world.saint_dominique)
    assert response.status_code == 201, response.content
    body = response.json()
    user = BaseUser.objects.get(email="secretaire@sd.sn")
    assert body["keycloak_id"] == user.keycloak_sub
    assert body["sync"] == "synchronise"
    assert user.admin_node == world.saint_dominique
    rep = kc.users[user.keycloak_sub]
    assert (rep["firstName"], rep["lastName"], rep["enabled"]) == ("Cécile", "Coly", True)
    assert rep["requiredActions"] == ["VERIFY_EMAIL", "UPDATE_PASSWORD"]
    assert kc.emails == [(user.keycloak_sub, ("VERIFY_EMAIL", "UPDATE_PASSWORD"))]
    event = AuditEvent.objects.get(action="compte.admin.creation")
    assert event.actor == world.admin and event.target_id == str(user.pk) and event.node == world.saint_dominique


def test_create_when_keycloak_is_down_writes_nothing(world, kc):
    kc.down = True
    response = create(world.admin, world.saint_dominique)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "keycloak_unavailable"
    assert not BaseUser.objects.filter(email="secretaire@sd.sn").exists()
    assert not AuditEvent.objects.filter(action="compte.admin.creation").exists()


def test_create_compensates_keycloak_when_database_fails(world, kc):
    response = create(world.admin, world.saint_dominique, phone_number="pas-un-numero")
    assert response.status_code == 400
    assert not BaseUser.objects.filter(email="secretaire@sd.sn").exists()
    assert kc.user_by_email("secretaire@sd.sn") is None  # compte Keycloak supprimé


def test_create_links_existing_keycloak_account_without_invitation(world, kc):
    sub = kc.seed(email="secretaire@sd.sn", email_verified=True)
    response = create(world.admin, world.saint_dominique)
    assert response.status_code == 201
    assert BaseUser.objects.get(email="secretaire@sd.sn").keycloak_sub == sub
    assert kc.emails == []


def test_create_duplicate_email_conflicts(world):
    response = create(world.admin, world.saint_dominique, email="fidele@test.sn")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "account_exists"


# --- Portée ----------------------------------------------------------------------------------


def test_cure_creates_only_in_his_parish(world):
    assert create(world.cure, world.saint_dominique).status_code == 201
    response = create(world.cure, world.sainte_therese, email="autre@st.sn")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "node_out_of_scope"


def test_fidele_has_no_admin_access(world):
    assert client_for(world.fidele).get(ACCOUNTS).status_code == 403


def test_scope_list_is_limited_to_the_perimeter(world):
    create(world.cure, world.saint_dominique)
    emails = {r["email"] for r in client_for(world.cure).get(ACCOUNTS, {"limit": 50}).json()["results"]}
    assert "secretaire@sd.sn" in emails
    assert "cure@thies.sn" not in emails and "fidele@test.sn" not in emails and "admin@numerisen.sn" not in emails
    chancery = {r["email"] for r in client_for(world.chancelier).get(ACCOUNTS, {"limit": 50}).json()["results"]}
    assert {"secretaire@sd.sn", "cure@sd.sn"} <= chancery
    assert "cure@thies.sn" not in chancery
    platform = {r["email"] for r in client_for(world.admin).get(ACCOUNTS, {"limit": 50}).json()["results"]}
    assert {"fidele@test.sn", "cure@thies.sn", "admin2@numerisen.sn"} <= platform


def test_never_above_oneself(world):
    # Un curé ne gère pas le compte d'un vicaire (nommé par l'évêque), un chancelier pas celui de l'évêque.
    response = client_for(world.cure).post(
        f"{ACCOUNTS}{world.vicaire.pk}/disable/", {"reason": "Départ de la paroisse"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_above_scope"
    response = client_for(world.chancelier).post(f"{ACCOUNTS}{world.eveque.pk}/logout/")
    assert response.status_code == 403
    # Hors périmètre : 404 (on ne révèle pas l'existence du compte).
    assert client_for(world.cure).get(f"{ACCOUNTS}{world.cure_thies.pk}/").status_code == 404
    assert client_for(world.chancelier).get(f"{ACCOUNTS}{world.admin2.pk}/").status_code == 404


def test_chancery_manages_parish_accounts(world, kc):
    create(world.cure, world.saint_dominique)
    secretary = BaseUser.objects.get(email="secretaire@sd.sn")
    response = client_for(world.chancelier).post(f"{ACCOUNTS}{world.cure.pk}/logout/")
    assert response.status_code == 200, response.content
    response = client_for(world.chancelier).post(f"{ACCOUNTS}{secretary.pk}/password-reset/")
    assert response.status_code == 200
    assert (secretary.keycloak_sub, ("UPDATE_PASSWORD",)) in kc.emails


# --- Modification, activation, suppression --------------------------------------------------


def test_update_is_pushed_to_keycloak(world, kc):
    url = f"{ACCOUNTS}{world.fidele.pk}/"
    response = client_for(world.admin).patch(url, {"first_name": "Marie-Thérèse", "email": "mt@test.sn"}, format="json")
    assert response.status_code == 200, response.content
    rep = kc.users[world.fidele.keycloak_sub]
    assert (rep["firstName"], rep["email"], rep["emailVerified"]) == ("Marie-Thérèse", "mt@test.sn", False)
    assert (world.fidele.keycloak_sub, ("VERIFY_EMAIL",)) in kc.emails
    world.fidele.refresh_from_db()
    assert world.fidele.email == "mt@test.sn" and not world.fidele.is_verified


def test_update_rolled_back_when_keycloak_fails(world, kc):
    kc.fail_on = {"user_update"}
    response = client_for(world.admin).patch(f"{ACCOUNTS}{world.fidele.pk}/", {"last_name": "Diouf"}, format="json")
    assert response.status_code == 503
    assert not Profile.objects.filter(user=world.fidele, last_name="Diouf").exists()


def test_disable_and_enable(world, kc):
    sub = world.fidele.keycloak_sub
    kc.sessions[sub] = [{"id": "s1"}]
    kc.brute_force[sub] = {"disabled": True, "numFailures": 5}
    url = f"{ACCOUNTS}{world.fidele.pk}/"
    assert client_for(world.admin).post(f"{url}disable/", {}).status_code == 400  # motif obligatoire
    response = client_for(world.admin).post(f"{url}disable/", {"reason": "Compte compromis"})
    assert response.json()["status"] == "desactive"
    assert kc.users[sub]["enabled"] is False and kc.sessions[sub] == []
    response = client_for(world.admin).post(f"{url}enable/", {})
    assert response.json()["status"] == "actif"
    assert kc.users[sub]["enabled"] is True and sub not in kc.brute_force
    actions = list(AuditEvent.objects.filter(target_id=str(world.fidele.pk)).values_list("action", flat=True))
    assert {"compte.admin.desactivation", "compte.admin.reactivation"} <= set(actions)


def test_disable_rolled_back_when_keycloak_is_down(world, kc):
    kc.down = True
    response = client_for(world.admin).post(f"{ACCOUNTS}{world.fidele.pk}/disable/", {"reason": "Compte compromis"})
    assert response.status_code == 503
    world.fidele.refresh_from_db()
    assert world.fidele.is_active


def test_self_and_last_platform_admin_guards(world, kc):
    response = client_for(world.admin).post(f"{ACCOUNTS}{world.admin.pk}/disable/", {"reason": "Essai sur moi"})
    assert response.json()["error"]["code"] == "self_action"
    BaseUser.objects.filter(pk=world.admin.pk).update(keycloak_platform_admin=False)
    response = client_for(world.admin).post(
        f"{ACCOUNTS}{world.admin2.pk}/platform-admin/", {"grant": False, "reason": "Fin de mission"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_platform_admin"


def test_delete_anonymizes_and_removes_keycloak_account(world, kc):
    sub = world.fidele.keycloak_sub
    url = f"{ACCOUNTS}{world.fidele.pk}/"
    wrong = client_for(world.admin).delete(url, {"confirm_email": "x@y.sn", "reason": "Demande RGPD"}, format="json")
    assert wrong.json()["error"]["code"] == "confirmation_mismatch"
    response = client_for(world.admin).delete(
        url, {"confirm_email": "fidele@test.sn", "reason": "Demande RGPD"}, format="json"
    )
    assert response.status_code == 204, response.content
    world.fidele.refresh_from_db()
    assert world.fidele.email.endswith("@deleted.invalid") and world.fidele.keycloak_sub is None
    assert sub not in kc.users
    assert AuditEvent.objects.filter(action="compte.admin.suppression", actor=world.admin).exists()


def test_delete_rolled_back_when_keycloak_fails(world, kc):
    kc.fail_on = {"user_delete"}
    url = f"{ACCOUNTS}{world.fidele.pk}/"
    response = client_for(world.admin).delete(
        url, {"confirm_email": "fidele@test.sn", "reason": "Demande RGPD"}, format="json"
    )
    assert response.status_code == 503
    world.fidele.refresh_from_db()
    assert world.fidele.email == "fidele@test.sn" and world.fidele.keycloak_sub


def test_delete_refused_with_active_office(world):
    url = f"{ACCOUNTS}{world.cure.pk}/"
    response = client_for(world.admin).delete(
        url, {"confirm_email": "cure@sd.sn", "reason": "Demande RGPD"}, format="json"
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "active_office"


# --- Actions Keycloak -------------------------------------------------------------------------


def test_detail_shows_live_keycloak_state(world, kc):
    sub = world.cure.keycloak_sub
    kc.credentials[sub].append({"id": "o1", "type": "otp"})
    kc.sessions[sub] = [
        {"id": "s1", "ipAddress": "10.0.0.1", "start": 1_790_000_000_000, "clients": {"c": "jangubi-web"}}
    ]
    body = client_for(world.admin).get(f"{ACCOUNTS}{world.cure.pk}/").json()
    assert body["role"] == "staff" and body["can_manage"] is True
    assert body["offices"][0]["office"] == "cure"
    state = body["keycloak"]
    assert state["available"] and state["otp"] and state["realm_roles"] == ["fidele"]
    assert state["sessions"][0]["clients"] == ["jangubi-web"]
    kc.down = True
    assert client_for(world.admin).get(f"{ACCOUNTS}{world.cure.pk}/").json()["keycloak"] == {"available": False}


def test_sessions_otp_brute_force_and_actions(world, kc):
    sub = world.cure.keycloak_sub
    kc.sessions[sub] = [{"id": "s1"}, {"id": "s2"}]
    kc.credentials[sub].append({"id": "o1", "type": "otp"})
    kc.brute_force[sub] = {"disabled": True, "numFailures": 8}
    admin = client_for(world.admin)
    url = f"{ACCOUNTS}{world.cure.pk}/"
    assert [s["id"] for s in admin.get(f"{url}sessions/").json()] == ["s1", "s2"]
    assert admin.delete(f"{url}sessions/s1/").status_code == 204
    assert admin.delete(f"{url}sessions/inconnue/").status_code == 400
    assert [s["id"] for s in kc.sessions[sub]] == ["s2"]
    assert admin.post(f"{url}otp-reset/", {"reason": "Téléphone perdu"}).status_code == 200
    assert all(c["type"] != "otp" for c in kc.credentials[sub])
    assert "CONFIGURE_TOTP" in kc.users[sub]["requiredActions"]
    assert admin.post(f"{url}brute-force-unlock/").status_code == 200
    assert sub not in kc.brute_force
    response = admin.post(f"{url}actions-email/", {"actions": ["UPDATE_PASSWORD", "CONFIGURE_TOTP"]}, format="json")
    assert response.status_code == 200
    assert admin.post(f"{url}actions-email/", {"actions": ["IMPERSONATE"]}, format="json").status_code == 400
    assert admin.post(f"{url}verify-email/").status_code == 200


def test_platform_only_actions(world, kc):
    create(world.cure, world.saint_dominique)
    secretary = BaseUser.objects.get(email="secretaire@sd.sn")
    cure = client_for(world.cure)
    response = cure.post(f"{ACCOUNTS}{secretary.pk}/mark-email-verified/", {"reason": "Vérifié en personne"})
    assert response.json()["error"]["code"] == "platform_only"
    response = cure.post(f"{ACCOUNTS}{secretary.pk}/platform-admin/", {"grant": True, "reason": "Essai interdit"})
    assert response.status_code == 403
    admin = client_for(world.admin)
    assert (
        admin.post(f"{ACCOUNTS}{secretary.pk}/mark-email-verified/", {"reason": "Vérifié en personne"}).status_code
        == 200
    )
    assert kc.users[secretary.keycloak_sub]["emailVerified"] is True
    response = admin.post(f"{ACCOUNTS}{secretary.pk}/platform-admin/", {"grant": True, "reason": "Équipe Numerisen"})
    assert response.json()["role"] == "platform_admin"
    assert secretary.keycloak_sub in kc.roles["platform_admin"]
    assert "CONFIGURE_TOTP" in kc.users[secretary.keycloak_sub]["requiredActions"]


def test_office_assignment_through_admin(world):
    create(world.cure, world.saint_dominique)
    secretary = BaseUser.objects.get(email="secretaire@sd.sn")
    url = f"{ACCOUNTS}{secretary.pk}/offices/"
    payload = {"office_type": "secretaire_paroissial", "node_id": str(world.saint_dominique.pk)}
    response = client_for(world.cure).post(url, payload, format="json")
    assert response.status_code == 201, response.content
    forbidden = {"office_type": "vicaire_paroissial", "node_id": str(world.saint_dominique.pk)}
    assert client_for(world.cure).post(url, forbidden, format="json").status_code == 403
    end = client_for(world.cure).post(f"{url}{response.json()['id']}/end/", {}, format="json")
    assert end.json()["status"] == "terminee"


# --- Keycloak → application : lecture des événements (Admin REST API) ------------------------


def test_events_poll_creates_updates_and_erases(world, kc):
    from apps.users.models import KeycloakSyncCursor
    from apps.users.tasks import keycloak_events_poll_task

    sub = kc.seed(email="awa@test.sn", first_name="Awa", email_verified=True)
    kc.record_user_event("REGISTER", sub)
    kc.record_user_event("LOGIN", sub)  # ignoré
    counts = keycloak_events_poll_task()
    assert counts["nouveaux"] == 2 and counts["traites"] == 1
    user = BaseUser.objects.get(keycloak_sub=sub)
    assert user.profile.first_name == "Awa"
    assert KeycloakSyncCursor.objects.get(name="utilisateur").last_event_ms > 0

    assert keycloak_events_poll_task()["nouveaux"] == 0  # curseur : rien de nouveau

    kc.users[world.fidele.keycloak_sub]["lastName"] = "Ndour"
    kc.record_admin_event("UPDATE", world.fidele.keycloak_sub)
    kc.record_admin_event("UPDATE", world.fidele.keycloak_sub)  # même compte : une seule relecture
    calls_before = kc.calls.count("user_get")
    keycloak_events_poll_task()
    assert kc.calls.count("user_get") - calls_before == 1
    assert Profile.objects.get(user=world.fidele).last_name == "Ndour"

    kc.user_delete(sub)
    kc.record_admin_event("DELETE", sub)
    keycloak_events_poll_task()
    user.refresh_from_db()
    assert user.email.endswith("@deleted.invalid")


def test_events_poll_keeps_cursor_when_keycloak_is_down(world, kc):
    from apps.users.models import KeycloakSyncCursor
    from apps.users.services_keycloak_sync import keycloak_events_poll

    sub = kc.seed(email="later@test.sn", email_verified=True)
    kc.record_user_event("REGISTER", sub)
    kc.fail_on = {"user_get"}
    counts = keycloak_events_poll()
    assert counts["echecs"] == 1
    assert KeycloakEvent.objects.get().status == "echec"
    kc.fail_on = set()
    keycloak_events_poll()  # l'événement en échec est retraité
    assert BaseUser.objects.filter(keycloak_sub=sub).exists()
    kc.down = True
    before = KeycloakSyncCursor.objects.get(name="utilisateur").last_event_ms
    keycloak_events_poll()
    cursor = KeycloakSyncCursor.objects.get(name="utilisateur")
    assert cursor.last_event_ms == before and cursor.last_error


def test_webhook_disabled_by_default(kc, settings):
    settings.KEYCLOAK_WEBHOOK_ENABLED = False
    assert _post_event({"uid": "e0", "type": "access.REGISTER", "userId": "x"}).status_code == 404


# --- Keycloak → application : webhook (option) ---------------------------------------------------------


def _post_event(payload, *, secret="secret-webhook-de-test"):
    body = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return APIClient().post(
        "/api/v1/integrations/keycloak/events/",
        body,
        content_type="application/json",
        HTTP_X_KEYCLOAK_SIGNATURE=signature,
    )


def test_webhook_rejects_bad_signature(kc):
    response = _post_event({"uid": "e1", "type": "access.REGISTER", "userId": "x"}, secret="faux")
    assert response.status_code == 403
    assert not KeycloakEvent.objects.exists()


def test_webhook_register_creates_account_and_is_idempotent(kc):
    sub = kc.seed(email="nouveau@test.sn", first_name="Awa", last_name="Sarr", email_verified=True)
    event = {"uid": "e1", "type": "access.REGISTER", "userId": sub}
    assert _post_event(event).status_code == 202
    user = BaseUser.objects.get(keycloak_sub=sub)
    assert user.email == "nouveau@test.sn" and user.profile.first_name == "Awa" and user.is_active
    assert _post_event(event).json()["duplicate"] is True
    assert KeycloakEvent.objects.get(uid="e1").status == "traite"


def test_webhook_admin_update_and_delete(world, kc):
    sub = world.fidele.keycloak_sub
    kc.users[sub].update({"firstName": "Moussa", "enabled": False})
    kc.roles["platform_admin"].add(sub)
    _post_event({"uid": "e2", "type": "admin.USER-UPDATE", "resourceType": "USER", "resourcePath": f"users/{sub}"})
    world.fidele.refresh_from_db()
    assert world.fidele.profile.first_name == "Moussa" and not world.fidele.is_active
    assert world.fidele.keycloak_platform_admin
    kc.user_delete(sub)
    _post_event({"uid": "e3", "type": "admin.USER-DELETE", "resourceType": "USER", "resourcePath": f"users/{sub}"})
    world.fidele.refresh_from_db()
    assert world.fidele.email.endswith("@deleted.invalid")


def test_webhook_ignores_logins(kc):
    assert _post_event({"uid": "e4", "type": "access.LOGIN", "userId": "x"}).json()["status"] == "ignore"


def test_webhook_never_links_unverified_email(world, kc):
    sub = kc.seed(email="fidele@test.sn", email_verified=False)
    _post_event({"uid": "e5", "type": "access.REGISTER", "userId": sub})
    world.fidele.refresh_from_db()
    assert world.fidele.keycloak_sub != sub
    assert world.fidele.keycloak_sync_error == "conflit_email"


# --- Réconciliation --------------------------------------------------------------------------


def test_reconcile_dry_run_then_apply(world, kc):
    only_kc = kc.seed(email="seul-kc@test.sn", email_verified=True)
    only_app = person("seul-app@test.sn")
    kc.users[world.fidele.keycloak_sub]["lastName"] = "Ndiaye"
    gone = linked(kc, person("parti@test.sn"))
    kc.user_delete(gone.keycloak_sub)

    out = io.StringIO()
    call_command("sync_keycloak", "--dry-run", stdout=out)
    assert "SIMULATION" in out.getvalue()
    run = KeycloakSyncRun.objects.get()
    kinds = {e["kind"] for e in run.report}
    assert kinds == {"keycloak_seul", "application_seule", "champs_differents", "supprime_dans_keycloak"}
    assert not BaseUser.objects.filter(keycloak_sub=only_kc).exists()  # rien de corrigé

    call_command("sync_keycloak", stdout=io.StringIO())
    assert BaseUser.objects.filter(keycloak_sub=only_kc).exists()
    only_app.refresh_from_db()
    assert only_app.keycloak_sub in kc.users
    assert Profile.objects.get(user=world.fidele).last_name == "Ndiaye"
    gone.refresh_from_db()
    assert gone.email.endswith("@deleted.invalid")
    rerun = json.loads(_json_run())
    assert rerun["counts"]["ecarts"] == 0


def _json_run() -> str:
    out = io.StringIO()
    call_command("sync_keycloak", "--dry-run", "--json", stdout=out)
    return out.getvalue()


def test_reconcile_deletion_threshold(world, kc, settings):
    settings.KEYCLOAK_RECONCILE_MAX_DELETIONS = 1
    victims = [linked(kc, person(f"p{i}@test.sn")) for i in range(2)]
    for v in victims:
        kc.user_delete(v.keycloak_sub)
    call_command("sync_keycloak", stdout=io.StringIO())
    for v in victims:
        v.refresh_from_db()
        assert not v.email.endswith("@deleted.invalid")
        assert v.keycloak_sync_error == "supprime_dans_keycloak"


def test_reconcile_when_keycloak_is_down(world, kc):
    kc.down = True
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("sync_keycloak", "--dry-run", stdout=io.StringIO())
    assert KeycloakSyncRun.objects.get().error


def test_periodic_task(world, kc):
    from apps.users.tasks import keycloak_accounts_reconcile_task

    kc.seed(email="tache@test.sn", email_verified=True)
    counts = keycloak_accounts_reconcile_task()
    assert counts["keycloak_seul"] == 1
    assert BaseUser.objects.filter(email="tache@test.sn").exists()


def test_profile_update_is_pushed(world, kc):
    from apps.users.services_me import me_profile_update

    me_profile_update(user=world.fidele, data={"first_name": "Moussa"})
    assert kc.users[world.fidele.keycloak_sub]["firstName"] == "Moussa"


# --- Tableau de bord, journal, export, état de la synchronisation -----------------------------


def test_dashboard_audit_export_and_sync_status(world, kc):
    create(world.cure, world.saint_dominique)
    client_for(world.admin).post(f"{ACCOUNTS}{world.fidele.pk}/disable/", {"reason": "Compte compromis"})
    dashboard = client_for(world.admin).get(f"{BASE}dashboard/").json()
    assert dashboard["comptes"]["desactives"] == 1 and dashboard["comptes"]["en_attente"] >= 1
    cure_dashboard = client_for(world.cure).get(f"{BASE}dashboard/").json()
    assert cure_dashboard["comptes"]["total"] == 2  # la secrétaire et le vicaire (visible, non géré)

    audit = client_for(world.admin).get(f"{BASE}audit/", {"action": "compte.admin."}).json()["results"]
    assert {a["action"] for a in audit} >= {"compte.admin.creation", "compte.admin.desactivation"}
    assert any(a["target_email"] == "fidele@test.sn" for a in audit)
    cure_audit = client_for(world.cure).get(f"{BASE}audit/").json()["results"]
    assert [a["action"] for a in cure_audit] == ["compte.admin.creation"]

    Profile.objects.filter(user__email="secretaire@sd.sn").update(first_name="=HYPERLINK()")
    response = client_for(world.cure).get(f"{ACCOUNTS}export/")
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0][:3] == ["id", "email", "prenom"]
    by_email = {r[1]: r for r in rows[1:]}
    assert set(by_email) == {"secretaire@sd.sn", "vicaire@sd.sn"}
    assert by_email["secretaire@sd.sn"][2] == "'=HYPERLINK()"

    assert client_for(world.cure).get(f"{BASE}sync/").status_code == 403
    run = client_for(world.admin).post(f"{BASE}sync/runs/", {"dry_run": True}, format="json").json()
    assert run["dry_run"] is True and run["success"] is True
    status = client_for(world.admin).get(f"{BASE}sync/").json()
    assert status["events_polling"] is True and status["reconciliations"][0]["id"] == run["id"]
    assert client_for(world.admin).get(f"{BASE}sync/runs/{run['id']}/").json()["report"] == run["report"]


def test_scope_endpoint(world):
    body = client_for(world.cure).get(f"{BASE}scope/").json()
    assert body["is_platform_admin"] is False and body["impersonation"] is False
    assert [n["name"] for n in body["nodes"]] == ["Saint-Dominique"]
    assert "UPDATE_PASSWORD" in body["required_actions"]
