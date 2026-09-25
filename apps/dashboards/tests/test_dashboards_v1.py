"""Tableaux de bord V1 (SRS §3.8 EF-DASH-01 à 03 ; RG-09, RG-11)."""

import datetime

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.confessions import services as confessions
from apps.dashboards.selectors import node_dashboard, platform_dashboard
from apps.hierarchy.tests.factories import make_place, nominate, person, priest
from apps.messaging.tests.factories import ConversationFactory, MessageFactory

pytestmark = pytest.mark.django_db
NOW = "2026-10-05 08:00:00"
SECRET = "ne doit jamais sortir 91c2"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def follower(tree, email: str, node):
    user = person(email)
    user.paroisse_suivie = node
    user.last_seen_on = timezone.localdate()
    user.save(update_fields=["paroisse_suivie", "last_seen_on"])
    return user


@pytest.fixture
def world(tree):
    tree.cure = priest("cure@sd.sn")
    tree.doyen = priest("doyen@pm.sn")
    tree.cure_thies = priest("cure@thies.sn")
    nominate(tree.cure, "cure", tree.saint_dominique)
    nominate(tree.doyen, "doyen", tree.doyenne)
    nominate(tree.cure_thies, "cure", tree.thies_parish)
    tree.awa = follower(tree, "awa@test.sn", tree.saint_dominique)
    tree.moussa = follower(tree, "moussa@test.sn", tree.sainte_therese)
    tree.fatou = follower(tree, "fatou@test.sn", tree.thies_parish)
    return tree


@freeze_time(NOW)
def test_node_dashboard_aggregates_subtree(world):
    conversation = ConversationFactory(participant_a=world.awa, participant_b=world.cure)
    first = MessageFactory(conversation=conversation, sender=world.awa, content=SECRET)
    reply = MessageFactory(conversation=conversation, sender=world.cure, content="Bonjour")
    type(first).objects.filter(pk=reply.pk).update(created_at=first.created_at + datetime.timedelta(hours=3))

    doyenne = node_dashboard(node=world.doyenne)
    assert doyenne["fideles"]["attached"] == 2  # Saint-Dominique + Sainte-Thérèse, pas Thiès
    assert doyenne["fideles"]["active"] == 2
    assert doyenne["messagerie"]["conversations"] == 1
    assert doyenne["messagerie"]["median_first_reply_hours"] == 3.0

    paroisse = node_dashboard(node=world.sainte_therese)
    assert paroisse["fideles"]["attached"] == 1
    assert paroisse["messagerie"]["conversations"] == 0


@freeze_time(NOW)
def test_node_dashboard_counts_confessions(world):
    place = make_place(world.saint_dominique, "Église")
    confessions.rule_create(
        priest=world.cure, place=place, weekday=2, start_time=datetime.time(17), end_time=datetime.time(17, 30)
    )
    slot = type(place).objects.get(pk=place.pk).confession_slots.order_by("starts_at").first()
    confessions.booking_create(slot=slot, person=world.awa)
    data = node_dashboard(node=world.saint_dominique)
    assert data["confessions"]["upcoming_booked"] == 1
    with freeze_time(slot.starts_at + datetime.timedelta(hours=1)):
        cache.clear()
        assert node_dashboard(node=world.saint_dominique)["confessions"]["booked"] == 1


@freeze_time(NOW)
def test_dashboard_never_reads_message_content_nor_names(world):
    conversation = ConversationFactory(participant_a=world.awa, participant_b=world.cure)
    MessageFactory(conversation=conversation, sender=world.awa, content=SECRET)
    with CaptureQueriesContext(connection) as ctx:
        data = node_dashboard(node=world.doyenne)
    message_queries = [q["sql"] for q in ctx.captured_queries if "messaging_message" in q["sql"]]
    assert message_queries
    assert all('"content"' not in sql for sql in message_queries)
    dumped = str(data)
    assert SECRET not in dumped
    assert "awa@test.sn" not in dumped


@freeze_time(NOW)
def test_api_node_dashboard_requires_capability_on_subtree(world):
    url = f"/api/v1/dashboards/nodes/{world.saint_dominique.pk}/"
    assert client_for(world.cure).get(url).status_code == 200
    assert client_for(world.doyen).get(url).status_code == 200  # héritage sur le sous-arbre
    assert client_for(world.cure_thies).get(url).status_code == 403
    assert client_for(world.awa).get(url).status_code == 403
    assert client_for(world.cure).get(f"/api/v1/dashboards/nodes/{world.doyenne.pk}/").status_code == 403
    assert client_for(world.cure).get(url, {"period": 12}).status_code == 400
    assert client_for(world.cure).get(url, {"period": 90}).data["period_days"] == 90


@freeze_time(NOW)
def test_node_dashboard_is_cached(world):
    first = node_dashboard(node=world.saint_dominique)
    follower(world, "nouveau@test.sn", world.saint_dominique)
    assert node_dashboard(node=world.saint_dominique) == first
    cache.clear()
    assert node_dashboard(node=world.saint_dominique)["fideles"]["attached"] == 2


@freeze_time(NOW)
def test_platform_dashboard(world):
    world.cure.last_mfa_on = timezone.localdate()
    world.cure.save(update_fields=["last_mfa_on"])
    data = platform_dashboard()
    assert data["staff"]["total"] == 3
    assert data["staff"]["with_mfa_30d"] == 1
    assert data["accounts"]["total"] >= 6
    assert "beat" in data and "health" in data


@freeze_time(NOW)
def test_api_platform_dashboard_reserved_to_platform(world, settings):
    settings.LEGACY_JWT_ENABLED = True
    admin = person("admin@numerisen.sn", is_superuser=True)
    assert client_for(admin).get("/api/v1/dashboards/platform/").status_code == 200
    assert client_for(world.cure).get("/api/v1/dashboards/platform/").status_code == 403


def test_keycloak_activity_stamp_writes_once_a_day(db):
    from apps.authentication.keycloak import activity_stamp

    user = person("stamp@test.sn")
    with CaptureQueriesContext(connection) as ctx:
        activity_stamp(user, mfa=True)
        activity_stamp(user, mfa=True)
    assert len([q for q in ctx.captured_queries if q["sql"].startswith("UPDATE")]) == 1
    user.refresh_from_db()
    assert user.last_seen_on == user.last_mfa_on == timezone.localdate()


@freeze_time(NOW)
def test_messaging_unanswered_after_48h(world):
    conversation = ConversationFactory(participant_a=world.awa, participant_b=world.cure)
    message = MessageFactory(conversation=conversation, sender=world.awa)
    type(message).objects.filter(pk=message.pk).update(created_at=timezone.now() - datetime.timedelta(hours=50))
    data = node_dashboard(node=world.saint_dominique)["messagerie"]
    assert (data["conversations"], data["unanswered_48h"], data["median_first_reply_hours"]) == (1, 1, None)


def test_activity_stamp_never_breaks_authentication(db, monkeypatch):
    from django.db import DatabaseError

    from apps.authentication import keycloak

    user = person("fragile@test.sn")

    def boom(*args, **kwargs):
        raise DatabaseError("indisponible")

    monkeypatch.setattr(type(user).objects, "filter", boom)
    keycloak.activity_stamp(user, mfa=False)  # ne lève pas
    assert user.last_seen_on is None
