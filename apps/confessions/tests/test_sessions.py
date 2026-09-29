"""Ouverture ponctuelle d'une séance de confession (lot V1-routes, G05)."""

import pytest
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.confessions.models import ConfessionSlot
from apps.hierarchy.models import AuditEvent
from apps.hierarchy.tests.factories import make_place, nominate, person, priest

pytestmark = pytest.mark.django_db
URL = "/api/v1/staff/confessions/sessions/"
NOW = "2026-10-05 08:00:00"  # lundi


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def world(tree):
    tree.place = make_place(tree.saint_dominique, "Église Saint-Dominique")
    tree.cure = priest("cure@sd.sn")
    tree.vicaire = priest("vicaire@sd.sn")
    tree.ailleurs = priest("pere@thies.sn")
    tree.secretaire = person("secretaire@sd.sn")
    nominate(tree.cure, "cure", tree.saint_dominique)
    nominate(tree.vicaire, "vicaire_paroissial", tree.saint_dominique)
    nominate(tree.ailleurs, "cure", tree.thies_parish)
    nominate(tree.secretaire, "secretaire_paroissial", tree.saint_dominique)
    return tree


def body(world, **kw):
    return {"place_id": world.place.pk, "date": "2026-10-10", "start_time": "09:00", "end_time": "10:00", "slot_minutes": 15, **kw}


@freeze_time(NOW)
def test_priest_opens_a_one_off_session(world):
    response = client_for(world.vicaire).post(URL, body(world), format="json")
    assert response.status_code == 201, response.content
    slots = response.json()
    assert len(slots) == 4 and all(s["status"] == "libre" for s in slots)
    assert ConfessionSlot.objects.filter(priest=world.vicaire, rule__isnull=True).count() == 4
    assert AuditEvent.objects.filter(action="confessions.seance_ouverture").exists()
    # Idempotent : rouvrir la même plage ne duplique rien.
    again = client_for(world.vicaire).post(URL, body(world), format="json")
    assert len(again.json()) == 4
    assert ConfessionSlot.objects.filter(priest=world.vicaire).count() == 4


@freeze_time(NOW)
def test_cure_opens_for_his_vicar_but_not_for_a_stranger(world):
    ok = client_for(world.cure).post(URL, body(world, priest_id=str(world.vicaire.pk)), format="json")
    assert ok.status_code == 201
    assert {s["priest_id"] for s in ok.json()} == {str(world.vicaire.pk)}
    ko = client_for(world.cure).post(URL, body(world, priest_id=str(world.ailleurs.pk)), format="json")
    assert ko.json()["error"]["code"] == "priest_not_confessor"


@freeze_time(NOW)
def test_rules_of_the_session(world):
    client = client_for(world.vicaire)
    assert client.post(URL, body(world, date="2026-10-01"), format="json").json()["error"]["code"] == "invalid_day"
    assert client.post(URL, body(world, end_time="08:00"), format="json").json()["error"]["code"] == "invalid_times"
    assert client_for(world.secretaire).post(URL, body(world), format="json").status_code == 403
    thies = make_place(world.thies_parish, "Cathédrale")
    assert client.post(URL, body(world, place_id=thies.pk), format="json").status_code == 403
