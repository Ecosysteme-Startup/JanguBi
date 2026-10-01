"""Épinglage d'une annonce avec date de fin (lot V1-routes, G06)."""

import datetime

import pytest
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.hierarchy.tests.factories import nominate, person
from apps.news.services import article_create, article_publish, article_unpublish
from apps.news.tests.factories import ArticleCategoryFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(tree):
    tree.category = ArticleCategoryFactory()
    tree.secretaire = person("secretaire@sd.sn")
    tree.other = person("secretaire@st.sn")
    nominate(tree.secretaire, "secretaire_paroissial", tree.saint_dominique)
    nominate(tree.other, "secretaire_paroissial", tree.sainte_therese)
    return tree


def published(world, title):
    article = article_create(
        author=world.secretaire, title=title, content="Texte.", category=world.category, node=world.saint_dominique
    )
    return article_publish(article=article, editor=world.secretaire)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_pinned_article_comes_first_until_its_end(world):
    older = published(world, "Kermesse")
    published(world, "Chorale")
    until = timezone.now() + datetime.timedelta(days=3)
    response = client_for(world.secretaire).post(
        f"/api/v1/staff/news/{older.pk}/pin/", {"until": until.isoformat()}, format="json"
    )
    assert response.status_code == 200, response.content
    assert response.json()["is_pinned"] is True

    titles = [a["title"] for a in APIClient().get("/api/v1/news/").json()["results"]]
    assert titles[0] == "Kermesse"
    assert APIClient().get("/api/v1/news/").json()["results"][0]["is_pinned"] is True

    with freeze_time(timezone.now() + datetime.timedelta(days=4)):
        titles = [a["title"] for a in APIClient().get("/api/v1/news/").json()["results"]]
        assert titles[0] == "Chorale"


def test_unpin_and_unpublish_clear_the_pin(world):
    article = published(world, "Kermesse")
    client = client_for(world.secretaire)
    until = (timezone.now() + datetime.timedelta(days=2)).isoformat()
    client.post(f"/api/v1/staff/news/{article.pk}/pin/", {"until": until}, format="json")
    response = client.delete(f"/api/v1/staff/news/{article.pk}/pin/")
    assert response.json()["is_pinned"] is False and response.json()["pinned_until"] is None

    client.post(f"/api/v1/staff/news/{article.pk}/pin/", {"until": until}, format="json")
    article.refresh_from_db()
    article_unpublish(article=article, editor=world.secretaire, reason="Erreur")
    article.refresh_from_db()
    assert article.pinned_until is None


@pytest.mark.parametrize("days, code", [(-1, "pin_until_past"), (61, "pin_until_too_far")])
def test_invalid_end_dates(world, days, code):
    article = published(world, "Kermesse")
    until = (timezone.now() + datetime.timedelta(days=days)).isoformat()
    response = client_for(world.secretaire).post(
        f"/api/v1/staff/news/{article.pk}/pin/", {"until": until}, format="json"
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code


def test_draft_cannot_be_pinned_and_other_parish_gets_404(world):
    draft = article_create(
        author=world.secretaire, title="Brouillon", content="x", category=world.category, node=world.saint_dominique
    )
    until = (timezone.now() + datetime.timedelta(days=2)).isoformat()
    response = client_for(world.secretaire).post(f"/api/v1/staff/news/{draft.pk}/pin/", {"until": until}, format="json")
    assert response.json()["error"]["code"] == "not_published"
    other = client_for(world.other).post(f"/api/v1/staff/news/{draft.pk}/pin/", {"until": until}, format="json")
    assert other.status_code == 404
