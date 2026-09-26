"""Délai indicatif par type d'acte, réglé par la paroisse (Paramètres, « Actes délivrés »).

Ordre de priorité de la date annoncée au fidèle : délai du type pour la paroisse → délai
global de la paroisse → réglage SLA hérité → défaut."""

import datetime

import pytest
from django.test import override_settings
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.documents.models import DocumentSlaSetting, DocumentTypeDelay
from apps.documents.services import document_request_create, document_type_delays_set
from apps.hierarchy.models import AuditEvent
from apps.hierarchy.tests.factories import nominate, person, priest

pytestmark = pytest.mark.django_db

FORM = {
    "document_type": "baptism",
    "reason": "religious_marriage",
    "requester_last_name": "Sène",
    "requester_first_names": "Jean-Baptiste",
    "date_of_birth": datetime.date(1994, 3, 12),
    "place_of_birth": "Dakar",
    "contact_phone": "+221774182690",
    "contact_email": "jb@test.sn",
    "father_last_name": "Sène",
    "mother_last_name": "Ndiaye",
    "sacrament_approximate_date": "1994",
    "sacrament_location": "Saint-Dominique",
    "consent_given": True,
}


@pytest.fixture
def world(tree):
    tree.fidele = person("jb@test.sn")
    tree.secretaire = person("secretaire@sd.sn")
    tree.cure_st = priest("cure@st.sn")
    nominate(tree.secretaire, "secretaire_paroissial", tree.saint_dominique)
    nominate(tree.cure_st, "cure", tree.sainte_therese)
    return tree


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def indicative_days(world, document_type: str = "baptism", **extra) -> dict:
    with freeze_time("2026-09-21 10:00:00"):
        r = document_request_create(
            requester=world.fidele,
            target_node=world.saint_dominique,
            data={**FORM, "document_type": document_type, **extra},
        )
        return client_for(world.fidele).get(f"/api/v1/documents/requests/{r.pk}/").data


def url(node) -> str:
    return f"/api/v1/staff/documents/nodes/{node.pk}/type-delays/"


# --- Ordre de priorité -----------------------------------------------------------------------


@override_settings(DOCUMENTS_DEFAULT_INDICATIVE_DAYS=7)
def test_default_applies_without_any_setting(world):
    assert indicative_days(world)["indicative_days"] == 7


def test_inherited_sla_applies_when_parish_sets_nothing(world):
    DocumentSlaSetting.objects.create(node=world.dakar, indicative_days=10)

    assert indicative_days(world)["indicative_days"] == 10


def test_parish_global_delay_wins_over_inherited_sla(world):
    DocumentSlaSetting.objects.create(node=world.dakar, indicative_days=10)
    world.saint_dominique.acts_delay_days = 4
    world.saint_dominique.save(update_fields=["acts_delay_days"])

    assert indicative_days(world)["indicative_days"] == 4


def test_type_delay_wins_over_parish_global_delay(world):
    # Arrange : diocèse 10 j, paroisse 4 j, et 2 j pour le baptême seulement.
    DocumentSlaSetting.objects.create(node=world.dakar, indicative_days=10)
    world.saint_dominique.acts_delay_days = 4
    world.saint_dominique.save(update_fields=["acts_delay_days"])
    DocumentTypeDelay.objects.create(node=world.saint_dominique, document_type="baptism", days=2)

    # Act
    baptism = indicative_days(world, "baptism")
    confirmation = indicative_days(world, "confirmation", reason="personal")

    # Assert : le type réglé l'emporte ; les autres types gardent le délai de la paroisse.
    assert baptism["indicative_days"] == 2 and baptism["estimated_ready_on"] == datetime.date(2026, 9, 23)
    assert confirmation["indicative_days"] == 4


def test_type_delay_of_another_parish_does_not_apply(world):
    DocumentTypeDelay.objects.create(node=world.sainte_therese, document_type="baptism", days=2)
    DocumentSlaSetting.objects.create(node=world.dakar, indicative_days=10)

    assert indicative_days(world)["indicative_days"] == 10


def test_type_delay_on_an_ancestor_is_not_inherited(world):
    # Le délai par type est celui de la paroisse du sacrement elle-même.
    DocumentTypeDelay.objects.create(node=world.dakar, document_type="baptism", days=2)
    DocumentSlaSetting.objects.create(node=world.dakar, indicative_days=10)

    assert indicative_days(world)["indicative_days"] == 10


# --- Service -------------------------------------------------------------------------------------


def test_service_sets_updates_and_clears_type_delays(world):
    node = world.saint_dominique

    document_type_delays_set(node=node, delays={"baptism": 3, "confirmation": 5}, actor=world.secretaire)
    after = document_type_delays_set(node=node, delays={"baptism": 6, "confirmation": None}, actor=world.secretaire)

    assert after == {"baptism": 6}
    assert AuditEvent.objects.filter(action="actes.delais_par_type").count() == 2


def test_service_refuses_out_of_range_other_type_and_foreign_node(world):
    with pytest.raises(ApplicationError) as out_of_range:
        document_type_delays_set(node=world.saint_dominique, delays={"baptism": 91}, actor=world.secretaire)
    with pytest.raises(ApplicationError) as other:
        document_type_delays_set(node=world.saint_dominique, delays={"other": 3}, actor=world.secretaire)
    with pytest.raises(PermissionDeniedError):
        document_type_delays_set(node=world.sainte_therese, delays={"baptism": 3}, actor=world.secretaire)

    assert out_of_range.value.code == "type_delay_out_of_range"
    assert other.value.code == "document_type_invalid"
    assert not DocumentTypeDelay.objects.exists()


def test_unchanged_delays_are_not_audited(world):
    document_type_delays_set(node=world.saint_dominique, delays={"baptism": 3}, actor=world.secretaire)
    document_type_delays_set(node=world.saint_dominique, delays={"baptism": 3}, actor=world.secretaire)

    assert AuditEvent.objects.filter(action="actes.delais_par_type").count() == 1


# --- API -----------------------------------------------------------------------------------------


@override_settings(DOCUMENTS_DEFAULT_INDICATIVE_DAYS=7)
def test_api_lists_every_configurable_type_with_default(world):
    DocumentTypeDelay.objects.create(node=world.saint_dominique, document_type="religious_marriage", days=12)

    response = client_for(world.secretaire).get(url(world.saint_dominique))

    assert response.status_code == 200
    assert response.data["default_days"] == 7
    items = {i["document_type"]: i["days"] for i in response.data["items"]}
    assert items == {
        "baptism": None,
        "first_communion": None,
        "confirmation": None,
        "religious_marriage": 12,
        "godparent": None,
    }


def test_api_put_updates_delays(world):
    response = client_for(world.secretaire).put(
        url(world.saint_dominique),
        {"items": [{"document_type": "baptism", "days": 3}, {"document_type": "godparent", "days": None}]},
        format="json",
    )

    assert response.status_code == 200
    assert {i["document_type"]: i["days"] for i in response.data["items"]}["baptism"] == 3
    assert DocumentTypeDelay.objects.get(document_type="baptism").days == 3


@pytest.mark.parametrize(
    "items",
    [
        [{"document_type": "baptism", "days": 0}],
        [{"document_type": "baptism", "days": 91}],
        [{"document_type": "other", "days": 3}],
        [{"document_type": "baptism", "days": 3}, {"document_type": "baptism", "days": 4}],
    ],
)
def test_api_validates_input(world, items):
    response = client_for(world.secretaire).put(url(world.saint_dominique), {"items": items}, format="json")

    assert response.status_code == 400
    assert not DocumentTypeDelay.objects.exists()


def test_api_requires_capability_on_the_node(world):
    fidele = client_for(world.fidele)
    foreign = client_for(world.cure_st)

    assert fidele.get(url(world.saint_dominique)).status_code == 403
    assert foreign.put(url(world.saint_dominique), {"items": []}, format="json").status_code == 403
    assert APIClient().get(url(world.saint_dominique)).status_code in (401, 403)


def test_api_unknown_node_is_404(world):
    response = client_for(world.secretaire).get("/api/v1/staff/documents/nodes/00000000-0000-0000-0000-000000000000/type-delays/")

    assert response.status_code == 404
