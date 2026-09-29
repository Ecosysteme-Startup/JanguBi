"""Intentions de messe (lot V1-routes) : aucun montant, aucun paiement."""

import pytest
from django.core.cache import cache
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.hierarchy.models import AuditEvent, Node
from apps.hierarchy.tests.factories import nominate, person, priest
from apps.intentions.enums import OFFERING_NOTICE
from apps.intentions.models import MassIntention
from apps.messaging.models import Notification

pytestmark = pytest.mark.django_db
NOW = "2026-09-27 09:00:00"


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture(autouse=True)
def _cache():
    cache.clear()


@pytest.fixture
def world(tree):
    Node.objects.filter(pk=tree.saint_dominique.pk).update(is_active_on_platform=True)
    tree.saint_dominique.refresh_from_db()
    tree.fidele = person("mt.diouf@test.sn")
    tree.secretaire = person("cecile.coly@sd.sn")
    tree.cure = priest("e.tine@sd.sn")
    tree.secretaire_st = person("secretaire@st.sn")
    nominate(tree.secretaire, "secretaire_paroissial", tree.saint_dominique)
    nominate(tree.cure, "cure", tree.saint_dominique)
    nominate(tree.secretaire_st, "secretaire_paroissial", tree.sainte_therese)
    return tree


def ask(world, **kw):
    payload = {
        "node": str(world.saint_dominique.pk),
        "kind": "defunt",
        "intention": "Pour le repos de l'âme de Joseph Diouf",
        "requested_date": "2026-10-04",
        "requested_mass": "Messe de 10 h",
        "is_anonymous": True,
        **kw,
    }
    return client_for(world.fidele).post("/api/v1/mass-intentions/", payload, format="json")


@freeze_time(NOW)
def test_full_cycle_without_any_amount(world):
    created = ask(world)
    assert created.status_code == 201, created.content
    data = created.json()
    assert data["status"] == "recue" and data["notice"] == OFFERING_NOTICE
    assert not any(k in data for k in ("amount", "montant", "offrande", "payment"))
    assert not any("amount" in f.name or "montant" in f.name for f in MassIntention._meta.get_fields())
    intention_id = data["id"]
    # Le secrétariat est prévenu, sans le texte de l'intention.
    notif = Notification.objects.get(user=world.secretaire, event_type="intention.recue")
    assert "Joseph" not in str(notif.payload)

    staff = client_for(world.secretaire)
    listing = staff.get("/api/v1/mass-intentions/parish/", {"node": str(world.saint_dominique.pk), "status": "recue"})
    assert listing.json()["count"] == 1
    assert listing.json()["results"][0]["announced_as"] == "Une personne"

    accepted = staff.post(
        f"/api/v1/mass-intentions/{intention_id}/accept/",
        {"scheduled_date": "2026-10-04", "scheduled_mass": "Messe de 10 h"},
        format="json",
    )
    assert accepted.status_code == 200 and accepted.json()["status"] == "planifiee"
    assert Notification.objects.filter(user=world.fidele, event_type="intention.planifiee").exists()

    too_early = staff.post(f"/api/v1/mass-intentions/{intention_id}/celebrate/")
    assert too_early.json()["error"]["code"] == "not_yet"
    with freeze_time("2026-10-04 12:00:00"):
        done = staff.post(f"/api/v1/mass-intentions/{intention_id}/celebrate/")
    assert done.json()["status"] == "celebree"
    mine = client_for(world.fidele).get("/api/v1/mass-intentions/mine/").json()
    assert mine["results"][0]["status"] == "celebree"
    assert AuditEvent.objects.filter(action__startswith="intention.").count() == 3


@freeze_time(NOW)
def test_decline_requires_a_reason_and_notifies(world):
    intention_id = ask(world).json()["id"]
    staff = client_for(world.secretaire)
    empty = staff.post(f"/api/v1/mass-intentions/{intention_id}/decline/", {"reason": " "}, format="json")
    assert empty.status_code == 400
    declined = staff.post(
        f"/api/v1/mass-intentions/{intention_id}/decline/", {"reason": "Messe déjà complète ce jour-là"}, format="json"
    )
    assert declined.json()["status"] == "refusee"
    assert Notification.objects.filter(user=world.fidele, event_type="intention.refusee").exists()


@freeze_time(NOW)
def test_scope_and_validation(world):
    intention_id = ask(world).json()["id"]
    other = client_for(world.secretaire_st)
    assert other.post(f"/api/v1/mass-intentions/{intention_id}/accept/", {"scheduled_date": "2026-10-04"}, format="json").status_code == 404
    assert other.get("/api/v1/mass-intentions/parish/", {"node": str(world.saint_dominique.pk)}).status_code == 403
    assert ask(world, requested_date="2026-09-01").json()["error"]["code"] == "date_past"
    assert ask(world, node=str(world.sainte_therese.pk)).json()["error"]["code"] == "parish_inactive"
    assert ask(world, node=str(world.doyenne.pk)).json()["error"]["code"] == "not_a_parish"
    assert client_for(world.fidele).get("/api/v1/mass-intentions/parish/", {"node": str(world.saint_dominique.pk)}).status_code == 403


@freeze_time(NOW)
def test_requester_cancels(world):
    intention_id = ask(world).json()["id"]
    cancelled = client_for(world.fidele).post(f"/api/v1/mass-intentions/{intention_id}/cancel/")
    assert cancelled.json()["status"] == "annulee"
    again = client_for(world.fidele).post(f"/api/v1/mass-intentions/{intention_id}/cancel/")
    assert again.json()["error"]["code"] == "invalid_transition"
    assert APIClient().get("/api/v1/mass-intentions/notice/").json() == {"notice": OFFERING_NOTICE}


@freeze_time(NOW)
def test_account_deletion_detaches_intentions(world):
    from apps.users.services_privacy import account_delete

    intention_id = ask(world).json()["id"]
    account_delete(user=world.fidele)
    obj = MassIntention.objects.get(pk=intention_id)
    assert obj.requester is None and obj.status == "annulee" and obj.is_anonymous
