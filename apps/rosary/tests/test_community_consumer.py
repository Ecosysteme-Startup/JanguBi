"""Consumer WebSocket du chapelet communautaire.

Couvre l'état initial envoyé à la connexion (roster nominatif), le refus
explicite d'une action réservée à l'initiateur, et le fait qu'une clôture
effectuée hors socket atteigne bien les sockets encore connectés.

Forme des tests : fonction **synchrone** sous ``django_db``, corps asynchrone
lancé par ``async_to_sync``. Ce détour n'est pas cosmétique — il place le code
``database_sync_to_async`` du consumer sur le thread du test (CurrentThreadExecutor
d'asgiref), donc sur SA connexion et SA transaction. Sans lui il faudrait
``transactional_db``, qui TRUNCATE toutes les tables et entre en conflit avec les
suites tournant en parallèle sur la base de test partagée.
"""

from itertools import count
from types import SimpleNamespace

import pytest
from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator

from apps.rosary.consumers import RosaryConsumer
from apps.rosary.models import CommunityRosary, RosaryParticipant
from apps.users.models import BaseUser

_phone_seq = count(300_000)

IN_MEMORY_CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


_STATE = {
    "fidele": ("laic", "aucun"),
    "diacre": ("clerc", "diacre_permanent"),
    "pretre": ("clerc", "pretre"),
}


def _make_user(email, pastoral_role="fidele"):
    user = BaseUser.objects.create_user(
        email=email,
        password="StrongPassw0rd!",
        phone_number=f"+221770{next(_phone_seq):06d}",
        is_active=True,
        is_verified=True,
    )
    user.etat_de_vie, user.degre_ordre = _STATE[pastoral_role]
    user.statut_verification = "verifie"
    user.save(update_fields=["etat_de_vie", "degre_ordre", "statut_verification"])
    return user


@pytest.fixture(autouse=True)
def _immediate_on_commit(monkeypatch):
    """Exécute les callbacks ``on_commit`` sur-le-champ.

    Les services diffusent **après commit** (une trame ne doit pas annoncer une
    écriture encore annulable). Or la transaction du test n'est jamais committée :
    sans ce raccourci, aucune diffusion ne partirait et les tests attendraient
    une trame qui n'arrive jamais.
    """
    monkeypatch.setattr(
        "django.db.transaction.on_commit", lambda func, using=None, robust=False: func()
    )


@pytest.fixture(autouse=True)
def _keep_test_connection(monkeypatch):
    """Neutralise ``close_old_connections`` autour des ``database_sync_to_async``.

    channels ferme les connexions « anciennes » à chaque entrée/sortie. En test,
    cette connexion est celle — transactionnelle — de pytest-django : la fermer
    en plein test casse le rollback et fait échouer tout ce qui suit avec
    ``InterfaceError: connection already closed``.
    """
    monkeypatch.setattr("channels.db.close_old_connections", lambda: None)


@pytest.fixture
def session(db, settings):
    # InMemoryChannelLayer : pas de Redis, et consumer et service partagent la
    # même instance via get_channel_layer().
    settings.CHANNEL_LAYERS = IN_MEMORY_CHANNEL_LAYERS

    pretre = _make_user("pretre.ws@example.com", "pretre")
    fidele = _make_user("fidele.ws@example.com", "fidele")
    rosary = CommunityRosary.objects.create(
        initiator=pretre, status=CommunityRosary.Status.ACTIVE, current_decade=2
    )
    # Participant déjà présent AVANT la connexion testée : c'est précisément ce
    # que la liste nominative ratait jusqu'ici.
    RosaryParticipant.objects.create(rosary=rosary, user=fidele)
    return SimpleNamespace(pretre=pretre, fidele=fidele, rosary=rosary)


def _communicator(rosary_id, user):
    communicator = WebsocketCommunicator(
        RosaryConsumer.as_asgi(), f"/ws/rosary/community/{rosary_id}/"
    )
    communicator.scope["url_route"] = {"kwargs": {"rosary_id": str(rosary_id)}}
    communicator.scope["user"] = user
    return communicator


async def _connect_and_drain(rosary_id, user):
    """Connecte puis consomme `session_state` + `participant_joined`."""
    communicator = _communicator(rosary_id, user)
    connected, _ = await communicator.connect()
    assert connected
    state = await communicator.receive_json_from()
    joined = await communicator.receive_json_from()
    return communicator, state, joined


@pytest.mark.django_db
def test_connect_sends_session_state_with_existing_roster(session):
    async def scenario():
        communicator, state, joined = await _connect_and_drain(
            session.rosary.pk, session.pretre
        )

        assert state["type"] == "session_state"
        assert state["current_decade"] == 2
        assert state["status"] == "active"
        assert state["initiator_email"] == session.pretre.email
        assert state["is_initiator"] is True
        # Le participant antérieur ET le nouvel arrivant.
        emails = {p["user_email"] for p in state["participants"]}
        assert emails == {session.fidele.email, session.pretre.email}
        assert state["participant_count"] == 2

        # La trame historique reste diffusée juste après : contrat inchangé.
        assert joined["type"] == "participant_joined"
        assert joined["user_email"] == session.pretre.email
        assert joined["participant_count"] == 2

        await communicator.disconnect()

    async_to_sync(scenario)()


@pytest.mark.django_db
def test_non_initiator_advance_gets_explicit_rejection(session):
    async def scenario():
        communicator, _, _ = await _connect_and_drain(session.rosary.pk, session.fidele)

        await communicator.send_json_to({"action": "advance"})
        frame = await communicator.receive_json_from()

        assert frame["type"] == "action_rejected"
        assert frame["action"] == "advance"
        assert frame["reason"]  # message user-safe, non vide

        await communicator.disconnect()

    async_to_sync(scenario)()

    session.rosary.refresh_from_db()
    assert session.rosary.current_decade == 2


@pytest.mark.django_db
def test_initiator_advance_broadcasts_decade(session):
    async def scenario():
        communicator, _, _ = await _connect_and_drain(session.rosary.pk, session.pretre)

        await communicator.send_json_to({"action": "advance"})
        frame = await communicator.receive_json_from()

        assert frame == {"type": "decade_advanced", "current_decade": 3}

        await communicator.disconnect()

    async_to_sync(scenario)()


@pytest.mark.django_db
def test_intention_over_socket_broadcasts_and_persists(session):
    async def scenario():
        communicator, _, _ = await _connect_and_drain(session.rosary.pk, session.fidele)

        await communicator.send_json_to({"action": "submit_intention", "text": "Pour la paix"})
        frame = await communicator.receive_json_from()

        assert frame == {
            "type": "intention_submitted",
            "text": "Pour la paix",
            "submitted_by": session.fidele.email,
        }

        await communicator.disconnect()

    async_to_sync(scenario)()

    assert session.rosary.intentions.count() == 1


@pytest.mark.django_db
def test_end_outside_socket_reaches_connected_participant(session):
    """Le scénario qui bloquait : l'initiateur clôt hors WebSocket."""
    from apps.rosary.community_services import community_rosary_end

    async def scenario():
        communicator, _, _ = await _connect_and_drain(session.rosary.pk, session.fidele)

        await database_sync_to_async(community_rosary_end)(
            rosary=session.rosary, user=session.pretre
        )

        frame = await communicator.receive_json_from()
        assert frame == {"type": "rosary_ended"}

        await communicator.disconnect()

    async_to_sync(scenario)()


@pytest.mark.django_db
def test_unknown_action_is_rejected(session):
    async def scenario():
        communicator, _, _ = await _connect_and_drain(session.rosary.pk, session.fidele)

        await communicator.send_json_to({"action": "teleport"})
        frame = await communicator.receive_json_from()

        assert frame["type"] == "action_rejected"
        assert frame["action"] == "teleport"

        await communicator.disconnect()

    async_to_sync(scenario)()


@pytest.mark.django_db
def test_connect_rejected_when_session_not_active(session):
    CommunityRosary.objects.filter(pk=session.rosary.pk).update(
        status=CommunityRosary.Status.COMPLETED
    )

    async def scenario():
        communicator = _communicator(session.rosary.pk, session.pretre)
        connected, code = await communicator.connect()

        assert connected is False
        assert code == 4004

    async_to_sync(scenario)()


@pytest.mark.django_db
def test_connect_rejected_for_anonymous_user(session):
    from django.contrib.auth.models import AnonymousUser

    async def scenario():
        communicator = _communicator(session.rosary.pk, AnonymousUser())
        connected, code = await communicator.connect()

        assert connected is False
        assert code == 4001

    async_to_sync(scenario)()
