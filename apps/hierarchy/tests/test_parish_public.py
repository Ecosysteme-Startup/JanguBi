"""Paramètres du secrétariat (horaires.gerer) et annuaire / fiche publics enrichis."""

from datetime import date, time

import pytest
from rest_framework.test import APIClient

from apps.hierarchy.models import AuditEvent
from apps.hierarchy.selectors_public import next_sunday
from apps.hierarchy.services import schedule_exception_create, schedule_replace
from apps.hierarchy.tests.factories import make_place, nominate, person, priest
from apps.users.tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db

BASE = "/api/v1/hierarchy"
PUBLIC = "/api/v1/public/nodes"


def client_for(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


@pytest.fixture
def world(tree):
    tree.secretaire = person("secretaire@sd.sn")
    tree.chancelier = person("chancelier@dakar.sn")
    tree.secretaire_thies = person("secretaire@thies.sn")
    nominate(tree.secretaire, "secretaire_paroissial", tree.saint_dominique)
    nominate(tree.chancelier, "chancelier", tree.dakar)
    nominate(tree.secretaire_thies, "secretaire_paroissial", tree.thies_parish)
    return tree


SETTINGS = {
    "phone": "+221 33 825 40 18",
    "email": "secretariat@saint-dominique.sn",
    "office_hours": [{"days": "Lun. – ven.", "hours": "9 h-12 h · 15 h 30-18 h"}, {"days": "Dimanche", "hours": "Fermé"}],
    "secretariat_public": True,
    "acts_delay_days": 3,
    "acts_welcome_message": "Munissez-vous d'une pièce d'identité.",
    "address": "Rue de Fatick, Point E",
}


# --- Paramètres : autorisation -----------------------------------------------------------


def test_secretary_updates_parish_life_settings_with_horaires_gerer(world):
    url = f"{BASE}/nodes/{world.saint_dominique.pk}/settings/"

    response = client_for(world.secretaire).patch(url, SETTINGS, format="json")

    assert response.status_code == 200
    assert response.data["phone"] == SETTINGS["phone"]
    assert response.data["office_hours"] == SETTINGS["office_hours"]
    assert response.data["acts_delay_days"] == 3
    assert client_for(world.secretaire).get(url).data["email"] == SETTINGS["email"]
    event = AuditEvent.objects.get(action="node.settings_update")
    assert event.node_id == world.saint_dominique.pk
    # Le journal garde les noms des champs, jamais leurs valeurs.
    assert "phone" in event.metadata["fields"]
    assert SETTINGS["phone"] not in str(event.metadata)


def test_secretary_cannot_patch_structural_fields(world):
    response = client_for(world.secretaire).patch(
        f"{BASE}/nodes/{world.saint_dominique.pk}/", {"name": "Autre nom"}, format="json"
    )
    assert response.status_code == 403


def test_structural_fields_are_ignored_by_the_settings_endpoint(world):
    url = f"{BASE}/nodes/{world.saint_dominique.pk}/settings/"

    client_for(world.secretaire).patch(url, {"name": "Autre nom", "code": "X", "status": "supprime"}, format="json")

    world.saint_dominique.refresh_from_db()
    assert world.saint_dominique.name == "Saint-Dominique"
    assert world.saint_dominique.status == "erige"


def test_chancellor_with_structure_gerer_can_also_update_settings(world):
    response = client_for(world.chancelier).patch(
        f"{BASE}/nodes/{world.saint_dominique.pk}/settings/", {"phone": "+221 33 000 00 00"}, format="json"
    )
    assert response.status_code == 200


def test_settings_are_scoped_to_the_node(world):
    url = f"{BASE}/nodes/{world.saint_dominique.pk}/settings/"

    assert client_for(world.secretaire_thies).get(url).status_code == 403
    assert client_for(world.secretaire_thies).patch(url, {"phone": "+221 1"}, format="json").status_code == 403


def test_settings_are_closed_to_faithful_and_anonymous(world):
    url = f"{BASE}/nodes/{world.saint_dominique.pk}/settings/"

    assert client_for(person()).get(url).status_code == 403
    assert client_for(person()).patch(url, {"phone": "+221 33"}, format="json").status_code == 403
    assert client_for().get(url).status_code in (401, 403)


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "pas-un-email"},
        {"phone": "appelez-moi"},
        {"acts_delay_days": 0},
        {"acts_delay_days": 365},
        {"office_hours": [{"days": "Lundi"}]},
        {"office_hours": [{"days": f"J{i}", "hours": "9 h"} for i in range(8)]},
    ],
)
def test_settings_validation(world, payload):
    response = client_for(world.secretaire).patch(
        f"{BASE}/nodes/{world.saint_dominique.pk}/settings/", payload, format="json"
    )
    assert response.status_code == 400


# --- Annuaire public ---------------------------------------------------------------------


def test_next_sunday():
    assert next_sunday(today=date(2026, 9, 24)) == date(2026, 9, 27)  # jeudi
    assert next_sunday(today=date(2026, 9, 27)) == date(2026, 9, 27)  # dimanche


def test_directory_adds_jurisdiction_and_sunday_masses(world, monkeypatch):
    monkeypatch.setattr("apps.hierarchy.apis.timezone.localdate", lambda: date(2026, 9, 24))
    church = make_place(world.saint_dominique, "Église", is_main=True)
    chapel = make_place(world.saint_dominique, "Chapelle")
    closed = make_place(world.saint_dominique, "Ancienne chapelle")
    closed.is_active = False
    closed.save()
    schedule_replace(
        place=church,
        items=[
            {"weekday": 6, "start_time": time(9, 30)},
            {"weekday": 6, "start_time": time(18, 30)},
            {"weekday": 0, "start_time": time(7, 0)},
            {"weekday": 6, "start_time": time(8, 0), "kind": "confession"},
        ],
    )
    schedule_replace(place=chapel, items=[{"weekday": 6, "start_time": time(9, 30)}])
    schedule_replace(place=closed, items=[{"weekday": 6, "start_time": time(6, 0)}])
    schedule_exception_create(place=church, date=date(2026, 9, 27), cancelled=True, start_time=time(18, 30))
    schedule_exception_create(place=chapel, date=date(2026, 9, 27), start_time=time(7, 0))

    response = client_for().get(f"{PUBLIC}/", {"diocese": str(world.dakar.pk), "q": "domi"})

    item = response.data["results"][0]
    assert item["parent_name"] == "Doyenné Plateau-Médina"
    assert item["deanery_name"] == "Doyenné Plateau-Médina"
    assert item["diocese_name"] == "Archidiocèse de Dakar"
    assert item["sunday_masses"] == ["07:00:00", "09:30:00"]
    assert item["parent_id"] == str(world.doyenne.pk)
    # L'annuaire ne publie aucune coordonnée du secrétariat.
    assert "phone" not in item and "secretariat" not in item


def test_directory_without_deanery(world):
    response = client_for().get(f"{PUBLIC}/", {"diocese": str(world.thies.pk)})

    item = response.data["results"][0]
    assert item["parent_name"] == "Diocèse de Thiès"
    assert item["deanery_name"] is None
    assert item["sunday_masses"] == []


def test_directory_does_not_query_per_node(world, django_assert_max_num_queries):
    for parish in (world.saint_dominique, world.sainte_therese, world.thies_parish):
        place = make_place(parish, "Église", is_main=True)
        schedule_replace(place=place, items=[{"weekday": 6, "start_time": time(9, 0)}])

    # transaction + comptage + page + juridiction + horaires + exceptions
    with django_assert_max_num_queries(7):
        response = client_for().get(f"{PUBLIC}/")
    assert response.data["count"] == 3


# --- Fiche publique ----------------------------------------------------------------------


def _named(user, first: str, last: str):
    ProfileFactory.create(user=user, first_name=first, last_name=last)
    return user


def test_sheet_hides_secretariat_until_published(world):
    client_for(world.secretaire).patch(
        f"{BASE}/nodes/{world.saint_dominique.pk}/settings/", {**SETTINGS, "secretariat_public": False}, format="json"
    )
    url = f"{PUBLIC}/by-code/{world.saint_dominique.code}/"

    hidden = client_for().get(url)
    client_for(world.secretaire).patch(
        f"{BASE}/nodes/{world.saint_dominique.pk}/settings/", {"secretariat_public": True}, format="json"
    )
    shown = client_for().get(url)

    assert hidden.data["secretariat"] is None
    assert shown.data["secretariat"] == {
        "phone": SETTINGS["phone"],
        "email": SETTINGS["email"],
        "office_hours": SETTINGS["office_hours"],
    }
    assert shown.data["acts"] == {"delay_days": 3, "welcome_message": SETTINGS["acts_welcome_message"]}
    assert shown.data["diocese_name"] == "Archidiocèse de Dakar"


def test_sheet_lists_public_clergy_name_and_office_only(world):
    cure = _named(priest("cure@sd.sn"), "Augustin", "Ndiaye")
    vicaire = _named(priest("vicaire@sd.sn"), "Emmanuel", "Tine")
    ancien = _named(priest("ancien@sd.sn"), "Robert", "Sagna")
    non_verifie = _named(priest("declare@sd.sn", verified=False), "Jean", "Faux")
    sans_nom = priest("anonyme@sd.sn")
    _named(world.secretaire, "Germaine", "Faye")  # laïque : pas dans le clergé
    nominate(cure, "cure", world.saint_dominique, start_date=date(2023, 9, 1), quality="administrateur")
    nominate(vicaire, "vicaire_paroissial", world.saint_dominique, start_date=date(2024, 9, 1))
    nominate(ancien, "vicaire_paroissial", world.saint_dominique, end_date=date(2021, 1, 1))
    nominate(non_verifie, "vicaire_paroissial", world.saint_dominique)
    nominate(sans_nom, "vicaire_paroissial", world.saint_dominique)
    nominate(_named(priest("thies@x.sn"), "Autre", "Paroisse"), "cure", world.thies_parish)

    response = client_for().get(f"{PUBLIC}/by-code/{world.saint_dominique.code}/")

    assert response.data["clergy"] == [
        {"name": "Augustin Ndiaye", "office": "Administrateur paroissial"},  # son titre réel
        {"name": "Emmanuel Tine", "office": "Vicaire paroissial"},
    ]
    assert "sd.sn" not in str(response.data)
