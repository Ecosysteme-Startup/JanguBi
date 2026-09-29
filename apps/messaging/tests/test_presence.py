"""Présence et « vu à » (plan V2 §4, lot B2) : compteur de connexions, vie privée, API, WebSocket."""

import asyncio
import datetime
from types import SimpleNamespace

import pytest
from channels.testing import WebsocketCommunicator
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.hierarchy.tests.factories import person, priest
from apps.messaging import services_presence
from apps.messaging.consumers import NotificationConsumer
from apps.messaging.models import MessageBlock
from apps.messaging.services_presence import (
    presence_connect,
    presence_contacts,
    presence_default_for,
    presence_disconnect,
    presence_heartbeat,
    presence_is_online,
    presence_setting_update,
    presence_visible,
)
from apps.users.models import BaseUser

from .factories import ConversationFactory

PRESENCE_URL = "/api/v1/messaging/presence/"
SETTING_URL = "/api/v1/me/presence/"


class FakeLayer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def group_send(self, group: str, message: dict) -> None:
        self.sent.append((group, message))


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def layer(monkeypatch) -> FakeLayer:
    fake = FakeLayer()
    monkeypatch.setattr(services_presence, "get_channel_layer", lambda: fake)
    return fake


@pytest.fixture
def world(db):
    """Le Père Emmanuel Tine échange avec Marie-Thérèse Diouf ; Awa n'a aucune conversation avec lui.
    Marie montre sa présence : sans cela, elle ne verrait pas celle du Père (réciprocité, décision 2)."""
    pere = priest("emmanuel.tine@sd.sn")
    marie = person("marie.therese.diouf@test.sn")
    marie.montrer_presence = True
    marie.save(update_fields=["montrer_presence"])
    awa = person("awa@test.sn")
    ConversationFactory(participant_a=pere, participant_b=marie)
    return SimpleNamespace(pere=pere, marie=marie, awa=awa)


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=BaseUser.objects.get(pk=user.pk))  # comme une vraie requête
    return client


# --- Réglage « montrer ma présence » ------------------------------------------------------------


def test_default_is_on_for_clergy_and_off_for_faithful(world):
    assert presence_default_for(world.pere) is True
    assert presence_default_for(world.marie) is False
    assert presence_default_for(world.awa) is False
    assert presence_visible(world.pere) is True
    assert presence_visible(world.awa) is False


def test_explicit_setting_overrides_default(world):
    world.marie.montrer_presence = True
    world.pere.montrer_presence = False
    world.awa.montrer_presence = None

    assert presence_visible(world.marie) is True
    assert presence_visible(world.pere) is False


# --- Interlocuteurs --------------------------------------------------------------------------------


def test_contacts_are_conversation_partners_without_blocks(world):
    assert presence_contacts(user=world.pere) == {world.marie.pk}
    assert presence_contacts(user=world.awa) == set()

    MessageBlock.objects.create(blocker=world.marie, blocked=world.pere)

    assert presence_contacts(user=world.pere) == set()
    assert presence_contacts(user=world.marie) == set()


# --- Compteur de connexions -------------------------------------------------------------------------


def test_two_connections_one_online_event_and_last_seen_on_last_close(world, layer):
    now = timezone.now().replace(microsecond=0)

    assert presence_connect(user=world.pere) is True
    assert presence_connect(user=world.pere) is False  # deuxième appareil
    assert presence_is_online(user_id=world.pere.pk)
    assert [g for g, _ in layer.sent] == [f"user_{world.marie.pk}"]
    assert layer.sent[0][1] == {
        "type": "presence.changed",
        "user_id": str(world.pere.pk),
        "visible": True,
        "online": True,
        "last_seen_at": None,
    }

    assert presence_disconnect(user=world.pere, now=now) is False
    assert presence_is_online(user_id=world.pere.pk)
    assert presence_disconnect(user=world.pere, now=now) is True

    assert not presence_is_online(user_id=world.pere.pk)
    assert BaseUser.objects.get(pk=world.pere.pk).last_seen_at == now
    offline = layer.sent[-1][1]
    assert offline["online"] is False
    assert offline["last_seen_at"] == now.isoformat()


def test_heartbeat_refreshes_and_recovers_after_expiry(world, layer):
    presence_connect(user=world.pere)
    assert presence_heartbeat(user=world.pere) is False

    cache.delete(f"presence:conn:{world.pere.pk}")  # 60 s sans battement
    assert not presence_is_online(user_id=world.pere.pk)

    assert presence_heartbeat(user=world.pere) is True
    assert presence_is_online(user_id=world.pere.pk)
    assert len(layer.sent) == 2


def test_hidden_presence_is_never_broadcast(world, layer):
    # Marie ne montre pas sa présence : ses connexions ne se devinent pas.
    BaseUser.objects.filter(pk=world.marie.pk).update(montrer_presence=None)
    world.marie.montrer_presence = None
    presence_connect(user=world.marie)
    presence_disconnect(user=world.marie)

    assert layer.sent == []
    assert BaseUser.objects.get(pk=world.marie.pk).last_seen_at is not None


def test_hiding_presence_broadcasts_an_erasing_event(world, layer, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        presence_setting_update(user=world.pere, montrer_presence=False)

    assert layer.sent == [
        (
            f"user_{world.marie.pk}",
            {
                "type": "presence.changed",
                "user_id": str(world.pere.pk),
                "visible": False,
                "online": None,
                "last_seen_at": None,
            },
        )
    ]


def test_no_broadcast_to_strangers(world, layer):
    presence_connect(user=world.awa)  # Awa n'a aucun interlocuteur

    assert layer.sent == []


# --- API ----------------------------------------------------------------------------------------------


def test_api_returns_only_conversation_partners(world, layer):
    presence_connect(user=world.pere)

    response = _client(world.marie).get(PRESENCE_URL, {"users": f"{world.pere.pk},{world.awa.pk}"})

    assert response.status_code == 200
    assert response.json() == [{"user_id": str(world.pere.pk), "visible": True, "online": True, "last_seen_at": None}]


def test_api_shows_last_seen_when_offline(world, layer):
    seen = timezone.now() - datetime.timedelta(minutes=12)
    BaseUser.objects.filter(pk=world.pere.pk).update(last_seen_at=seen)

    rows = _client(world.marie).get(PRESENCE_URL, {"users": str(world.pere.pk)}).json()

    assert rows[0]["online"] is False
    assert rows[0]["last_seen_at"] is not None


def test_api_hides_presence_of_someone_who_does_not_show_it(world, layer):
    presence_connect(user=world.marie)
    BaseUser.objects.filter(pk=world.marie.pk).update(last_seen_at=timezone.now(), montrer_presence=False)

    rows = _client(world.pere).get(PRESENCE_URL, {"users": str(world.marie.pk)}).json()

    assert rows == [{"user_id": str(world.marie.pk), "visible": False, "online": None, "last_seen_at": None}]


def test_api_stranger_gets_nothing(world, layer):
    presence_connect(user=world.pere)

    response = _client(world.awa).get(PRESENCE_URL, {"users": str(world.pere.pk)})

    assert response.status_code == 200
    assert response.json() == []


def test_api_validates_the_list(world):
    client = _client(world.marie)

    assert client.get(PRESENCE_URL).status_code == 400
    assert client.get(PRESENCE_URL, {"users": "pas-un-uuid"}).status_code == 400
    too_many = ",".join(str(world.pere.pk) for _ in range(51))
    assert client.get(PRESENCE_URL, {"users": too_many}).status_code == 400
    assert APIClient().get(PRESENCE_URL, {"users": str(world.pere.pk)}).status_code == 401


def test_api_setting_get_and_update(world, layer):
    client = _client(world.awa)

    assert client.get(SETTING_URL).json() == {"montrer_presence": None, "effective": False, "default": False}

    response = client.put(SETTING_URL, {"montrer_presence": True}, format="json")

    assert response.status_code == 200
    assert response.json() == {"montrer_presence": True, "effective": True, "default": False}
    assert BaseUser.objects.get(pk=world.awa.pk).montrer_presence is True


# --- Réciprocité (décision 2 du 29/09/2026) -------------------------------------------------------


def test_reciprocity_hidden_viewer_reads_only_unknown(world, layer):
    """Qui masque sa présence ne voit plus celle des autres : ni « en ligne » ni « vu à »."""
    presence_connect(user=world.pere)
    BaseUser.objects.filter(pk=world.marie.pk).update(montrer_presence=False)

    rows = _client(world.marie).get(PRESENCE_URL, {"users": f"{world.pere.pk},{world.awa.pk}"}).json()

    assert rows == [{"user_id": str(world.pere.pk), "visible": False, "online": None, "last_seen_at": None}]


def test_reciprocity_default_faithful_sees_nothing(world, layer):
    """Un fidèle au réglage par défaut (présence non montrée) ne voit pas celle du Père."""
    presence_connect(user=world.pere)
    BaseUser.objects.filter(pk=world.marie.pk).update(montrer_presence=None)

    rows = _client(world.marie).get(PRESENCE_URL, {"users": str(world.pere.pk)}).json()

    assert rows[0]["visible"] is False and rows[0]["online"] is None


def test_reciprocity_no_event_sent_to_a_hidden_viewer(world, layer):
    BaseUser.objects.filter(pk=world.marie.pk).update(montrer_presence=False)

    presence_connect(user=world.pere)
    presence_disconnect(user=world.pere)

    assert layer.sent == []


def test_reciprocity_showing_again_restores_events(world, layer, django_capture_on_commit_callbacks):
    marie = BaseUser.objects.get(pk=world.marie.pk)
    with django_capture_on_commit_callbacks(execute=True):
        presence_setting_update(user=marie, montrer_presence=False)
    presence_connect(user=world.pere)
    assert [g for g, m in layer.sent if m["user_id"] == str(world.pere.pk)] == []

    with django_capture_on_commit_callbacks(execute=True):
        presence_setting_update(user=marie, montrer_presence=True)
    presence_disconnect(user=world.pere)

    assert [g for g, m in layer.sent if m["user_id"] == str(world.pere.pk)] == [f"user_{marie.pk}"]


# --- WebSocket ------------------------------------------------------------------------------------------


@pytest.fixture
def in_memory_layer(settings, monkeypatch):
    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    monkeypatch.setattr("django.db.transaction.on_commit", lambda func, using=None, robust=False: func())


def _socket(user) -> WebsocketCommunicator:
    communicator = WebsocketCommunicator(NotificationConsumer.as_asgi(), "/ws/notifications/")
    communicator.scope["user"] = user
    return communicator


@pytest.mark.django_db(transaction=True)
def test_websocket_presence_flow(in_memory_layer):
    pere = priest("pere.ws@sd.sn")
    marie = person("marie.ws@test.sn")
    BaseUser.objects.filter(pk=marie.pk).update(montrer_presence=True)
    marie.montrer_presence = True
    ConversationFactory(participant_a=pere, participant_b=marie)

    async def scenario():
        marie_socket = _socket(marie)
        assert (await marie_socket.connect())[0]

        pere_socket = _socket(pere)
        assert (await pere_socket.connect())[0]
        online = await marie_socket.receive_json_from(timeout=2)
        assert online["type"] == "presence.changed"
        assert online["user_id"] == str(pere.pk)
        assert online["online"] is True

        await pere_socket.send_json_to({"type": "presence.ping"})
        assert await pere_socket.receive_json_from(timeout=2) == {"type": "presence.pong"}

        await pere_socket.disconnect()
        offline = await marie_socket.receive_json_from(timeout=2)
        assert offline["online"] is False
        assert offline["last_seen_at"]

        # Marie se déconnecte à son tour (le Père est déjà parti : rien à recevoir).
        await marie_socket.disconnect()

    asyncio.run(scenario())
    assert BaseUser.objects.get(pk=pere.pk).last_seen_at is not None
