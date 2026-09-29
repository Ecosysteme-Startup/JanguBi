"""Tâches du jour d'une paroisse (lot V1-routes, G01)."""

import datetime

import pytest
from django.core.cache import cache
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.confessions import services as confessions_services
from apps.documents.tests.factories import DocumentRequestFactory
from apps.hierarchy.models import Node
from apps.hierarchy.tests.factories import Tree, make_place, nominate, person, priest
from apps.intentions.models import MassIntention
from apps.news.services import article_create
from apps.news.tests.factories import ArticleCategoryFactory

pytestmark = pytest.mark.django_db
URL = "/api/v1/staff/taches-du-jour/"


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def world(db):
    cache.clear()
    w = Tree()
    Node.objects.filter(pk=w.saint_dominique.pk).update(is_active_on_platform=True)
    w.place = make_place(w.saint_dominique, "Église Saint-Dominique")
    w.cure = priest("cure@sd.sn")
    w.secretaire = person("secretaire@sd.sn")
    w.fidele = person("fidele@test.sn")
    w.autre = person("secretaire@st.sn")
    nominate(w.cure, "cure", w.saint_dominique)
    nominate(w.secretaire, "secretaire_paroissial", w.saint_dominique)
    nominate(w.autre, "secretaire_paroissial", w.sainte_therese)
    return w


@freeze_time("2026-09-26 08:00:00")  # samedi
def test_secretary_sees_her_counts_without_penitents(world):
    DocumentRequestFactory.create_batch(2, target_node=world.saint_dominique)
    DocumentRequestFactory(target_node=world.saint_dominique, status="info_requested")
    DocumentRequestFactory(target_node=world.sainte_therese)
    article_create(
        author=world.secretaire, title="Kermesse", content="x", category=ArticleCategoryFactory(),
        node=world.saint_dominique, is_sunday_notice=True, sunday_date=datetime.date(2026, 9, 27),
    )  # fmt: skip
    MassIntention.objects.create(
        requester=world.fidele, node=world.saint_dominique, kind="defunt", intention="x",
        requested_date=datetime.date(2026, 9, 27),
    )  # fmt: skip
    confessions_services.session_open(
        actor=world.cure, place=world.place, day=datetime.date(2026, 9, 26),
        start_time=datetime.time(10, 0), end_time=datetime.time(10, 30), slot_minutes=15,
    )  # fmt: skip

    response = client_for(world.secretaire).get(URL, {"node": str(world.saint_dominique.pk)})
    assert response.status_code == 200, response.content
    body = response.json()
    counts = {t["code"]: t["count"] for t in body["tasks"]}
    assert counts["demandes_a_traiter"] == 2
    assert counts["demandes_complement"] == 1
    assert counts["quetes_a_confirmer"] == 0
    assert counts["annonces_a_publier"] == 1 and counts["annonces_du_dimanche"] == 1
    assert counts["intentions_a_planifier"] == 1
    assert counts["confessions_du_jour"] == 2
    assert set(body["confessions"][0]) == {"slot_id", "starts_at", "ends_at", "place_name", "priest_name", "reserved"}


def test_rights(world):
    assert client_for(world.autre).get(URL, {"node": str(world.saint_dominique.pk)}).status_code == 403
    assert client_for(world.fidele).get(URL, {"node": str(world.saint_dominique.pk)}).status_code == 403
