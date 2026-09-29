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
    assert (
        other.post(
            f"/api/v1/mass-intentions/{intention_id}/accept/", {"scheduled_date": "2026-10-04"}, format="json"
        ).status_code
        == 404
    )
    assert other.get("/api/v1/mass-intentions/parish/", {"node": str(world.saint_dominique.pk)}).status_code == 403
    assert ask(world, requested_date="2026-09-01").json()["error"]["code"] == "date_past"
    assert ask(world, node=str(world.sainte_therese.pk)).json()["error"]["code"] == "parish_inactive"
    assert ask(world, node=str(world.doyenne.pk)).json()["error"]["code"] == "not_a_parish"
    assert (
        client_for(world.fidele)
        .get("/api/v1/mass-intentions/parish/", {"node": str(world.saint_dominique.pk)})
        .status_code
        == 403
    )


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


def _sunday_masses(world):
    import datetime

    from apps.hierarchy.models import MassSchedule, PlaceOfWorship

    place = PlaceOfWorship.objects.create(node=world.saint_dominique, name="Église Saint-Dominique", is_main=True)
    for hour in (8, 10):
        MassSchedule.objects.create(place=place, kind="messe", weekday=6, start_time=datetime.time(hour, 0))
    MassSchedule.objects.create(place=place, kind="confession", weekday=6, start_time=datetime.time(17, 0))
    return place


@freeze_time(NOW)
def test_request_without_precise_date(world):
    created = ask(world, requested_date=None)
    assert created.status_code == 201, created.content
    assert created.json()["requested_date"] is None
    payload = {
        k: v
        for k, v in {
            "node": str(world.saint_dominique.pk),
            "kind": "particuliere",
            "intention": "Pour ma famille",
        }.items()
    }
    assert client_for(world.fidele).post("/api/v1/mass-intentions/", payload, format="json").status_code == 201


@freeze_time(NOW)
def test_masses_of_day_cap_and_sheet(world):
    place = _sunday_masses(world)
    staff = client_for(world.secretaire)
    node = str(world.saint_dominique.pk)
    assert staff.get("/api/v1/mass-intentions/parish/reglages/", {"node": node}).json()["max_per_mass"] == 5
    assert (
        staff.patch(
            "/api/v1/mass-intentions/parish/reglages/", {"node": node, "max_per_mass": 0}, format="json"
        ).status_code
        == 400
    )
    assert (
        staff.patch(
            "/api/v1/mass-intentions/parish/reglages/", {"node": node, "max_per_mass": 2}, format="json"
        ).json()["max_per_mass"]
        == 2
    )

    ids = [ask(world, intention=f"Intention {i}", is_anonymous=i != 0).json()["id"] for i in range(3)]
    body = {
        "scheduled_date": "2026-10-04",
        "scheduled_time": "10:00",
        "place_id": place.pk,
        "scheduled_mass": "Messe de 10 h",
    }
    for intention_id in ids[:2]:
        assert staff.post(f"/api/v1/mass-intentions/{intention_id}/accept/", body, format="json").status_code == 200
    full = staff.post(f"/api/v1/mass-intentions/{ids[2]}/accept/", body, format="json")
    assert full.json()["error"]["code"] == "mass_full"
    no_place = staff.post(
        f"/api/v1/mass-intentions/{ids[2]}/accept/",
        {**body, "place_id": None, "scheduled_time": "08:00"},
        format="json",
    )
    assert no_place.json()["error"]["code"] == "place_required"
    # Déplacer une intention déjà retenue sur la même messe ne compte pas deux fois.
    assert staff.post(f"/api/v1/mass-intentions/{ids[0]}/accept/", body, format="json").status_code == 200

    day = staff.get("/api/v1/mass-intentions/parish/messes/", {"node": node, "date": "2026-10-04"}).json()
    assert [m["label"] for m in day["masses"]] == ["Messe de 8 h", "Messe de 10 h"]
    ten = day["masses"][1]
    assert ten["intentions_count"] == 2 and ten["is_full"] and ten["remaining"] == 0 and ten["max_intentions"] == 2
    assert day["masses"][0]["intentions_count"] == 0

    sheet = staff.get("/api/v1/mass-intentions/parish/feuille/", {"node": node, "date": "2026-10-04"})
    assert sheet.status_code == 200
    texts = [i["intention"] for i in sheet.json()["masses"][1]["intentions"]]
    assert sorted(texts) == ["Intention 0", "Intention 1"]
    assert "montant" not in sheet.content.decode() and "amount" not in sheet.content.decode()
    assert {i["announced_as"] for i in sheet.json()["masses"][1]["intentions"]} >= {"Une personne"}

    other = client_for(world.secretaire_st)
    assert other.get("/api/v1/mass-intentions/parish/feuille/", {"node": node, "date": "2026-10-04"}).status_code == 403
    assert (
        other.patch(
            "/api/v1/mass-intentions/parish/reglages/", {"node": node, "max_per_mass": 3}, format="json"
        ).status_code
        == 403
    )


@freeze_time(NOW)
def test_dynamic_caps_parish_none_and_per_mass_override(world):
    place = _sunday_masses(world)
    staff = client_for(world.secretaire)
    node = str(world.saint_dominique.pk)
    url_cap = "/api/v1/mass-intentions/parish/messes/plafond/"
    body = {"scheduled_date": "2026-10-04", "scheduled_time": "10:00", "place_id": place.pk}

    # Paroisse sans plafond.
    res = staff.patch("/api/v1/mass-intentions/parish/reglages/", {"node": node, "max_per_mass": None}, format="json")
    assert res.status_code == 200 and res.json()["max_per_mass"] is None
    assert staff.get("/api/v1/mass-intentions/parish/reglages/", {"node": node}).json()["max_per_mass"] is None
    ids = [ask(world, intention=f"I{i}").json()["id"] for i in range(4)]
    for intention_id in ids[:3]:
        assert staff.post(f"/api/v1/mass-intentions/{intention_id}/accept/", body, format="json").status_code == 200
    day = staff.get("/api/v1/mass-intentions/parish/messes/", {"node": node, "date": "2026-10-04"}).json()
    ten = day["masses"][1]
    assert day["max_per_mass"] is None
    assert ten["max_intentions"] is None and ten["remaining"] is None and ten["is_full"] is False
    assert ten["cap_source"] == "paroisse" and ten["intentions_count"] == 3

    # Plafond propre à l'horaire du dimanche 10 h : 3, la 4e est refusée.
    weekly = {"node": node, "place_id": place.pk, "start_time": "10:00", "weekday": 6, "max_intentions": 3}
    assert staff.put(url_cap, weekly, format="json").status_code == 200
    assert (
        staff.post(f"/api/v1/mass-intentions/{ids[3]}/accept/", body, format="json").json()["error"]["code"]
        == "mass_full"
    )
    ten = staff.get("/api/v1/mass-intentions/parish/messes/", {"node": node, "date": "2026-10-04"}).json()["masses"][1]
    assert ten["max_intentions"] == 3 and ten["is_full"] and ten["remaining"] == 0 and ten["cap_source"] == "horaire"

    # Messe datée sans plafond : l'emporte sur l'horaire.
    dated = {"node": node, "place_id": place.pk, "start_time": "10:00", "date": "2026-10-04", "max_intentions": None}
    assert staff.put(url_cap, dated, format="json").json()["max_intentions"] is None
    assert staff.post(f"/api/v1/mass-intentions/{ids[3]}/accept/", body, format="json").status_code == 200
    ten = staff.get("/api/v1/mass-intentions/parish/messes/", {"node": node, "date": "2026-10-04"}).json()["masses"][1]
    assert ten["cap_source"] == "date" and ten["max_intentions"] is None and not ten["is_full"]
    assert len(staff.get(url_cap, {"node": node}).json()) == 2

    # Retrait : on revient à l'horaire, puis à la paroisse.
    assert (
        staff.delete(f"{url_cap}?node={node}&place_id={place.pk}&start_time=10:00&date=2026-10-04").status_code == 204
    )
    ten = staff.get("/api/v1/mass-intentions/parish/messes/", {"node": node, "date": "2026-10-04"}).json()["masses"][1]
    assert ten["cap_source"] == "horaire" and ten["remaining"] == 0
    assert staff.delete(f"{url_cap}?node={node}&place_id={place.pk}&start_time=10:00&weekday=6").status_code == 204
    assert staff.get(url_cap, {"node": node}).json() == []

    # Erreurs et droits.
    both = {**weekly, "date": "2026-10-04"}
    assert staff.put(url_cap, both, format="json").json()["error"]["code"] == "weekday_or_date"
    assert staff.put(url_cap, {**weekly, "max_intentions": 51}, format="json").status_code == 400
    assert client_for(world.secretaire_st).put(url_cap, weekly, format="json").status_code == 403
    assert AuditEvent.objects.filter(action="intention.plafond_messe").exists()
