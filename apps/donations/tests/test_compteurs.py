"""Équipe des compteurs de quête (lot V1-routes, G08) : staff/dons/compteurs/."""

import pytest

from apps.donations import services
from apps.donations.models import CollectionCounter
from apps.donations.tests.conftest import TODAY, client_for
from apps.hierarchy.models import AuditEvent

pytestmark = pytest.mark.django_db
URL = "/api/v1/staff/dons/compteurs/"


def test_secretary_builds_the_team_and_sees_recent_names(world, fund):
    services.cash_collection_create(
        actor=world.secretaire, node=world.sd, fund=fund, mass_date=TODAY, mass_label="Messe de 10 h",
        amount=150_000, counter_one="Awa Faye", counter_two="Jean Diouf",
    )  # fmt: skip
    client = client_for(world.secretaire)
    created = client.post(URL, {"node": str(world.sd.pk), "nom": "  Awa   Faye "}, format="json")
    assert created.status_code == 201, created.content
    assert created.json()["nom"] == "Awa Faye"

    listing = client.get(URL, {"node": str(world.sd.pk)})
    assert listing.status_code == 200
    body = listing.json()
    assert [c["nom"] for c in body["compteurs"]] == ["Awa Faye"]
    assert body["noms_recents"] == ["Jean Diouf"]
    assert AuditEvent.objects.filter(action="dons.compteur_ajout").exists()


def test_duplicate_name_is_refused_case_insensitively(world):
    client = client_for(world.secretaire)
    client.post(URL, {"node": str(world.sd.pk), "nom": "Awa Faye"}, format="json")
    again = client.post(URL, {"node": str(world.sd.pk), "nom": "awa faye"}, format="json")
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "counter_duplicate"


def test_rename_and_remove_keep_history(world):
    client = client_for(world.cure)
    counter_id = client.post(URL, {"node": str(world.sd.pk), "nom": "Awa Fay"}, format="json").json()["id"]
    renamed = client.patch(f"{URL}{counter_id}/", {"nom": "Awa Faye"}, format="json")
    assert renamed.json()["nom"] == "Awa Faye"
    assert client.delete(f"{URL}{counter_id}/").status_code == 204
    counter = CollectionCounter.objects.get(pk=counter_id)
    assert counter.is_active is False
    assert client.get(URL, {"node": str(world.sd.pk)}).json()["compteurs"] == []
    # Retiré puis ré-ajouté : pas de conflit avec l'ancien.
    assert client.post(URL, {"node": str(world.sd.pk), "nom": "Awa Faye"}, format="json").status_code == 201


def test_other_parish_is_forbidden(world):
    response = client_for(world.autre_cure).get(URL, {"node": str(world.sd.pk)})
    assert response.status_code == 403
    assert client_for(world.eveque).get(URL, {"node": str(world.sd.pk)}).status_code == 403
