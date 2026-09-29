"""SSE : format, reprise Last-Event-ID, battement, flux des dons (droits et événements)."""

import asyncio
import datetime

import pytest
from asgiref.sync import sync_to_async
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.authentication.ws_tickets import ws_ticket_issue
from apps.donations import services as dons_services
from apps.donations.enums import DonationStatus, StatusSource

# Mise en place partagée avec les tests des dons (paroisse Saint-Dominique, fonds ouvert).
from apps.donations.tests.conftest import fund, pay, tree, world  # noqa: F401
from apps.realtime import dons as realtime_dons
from apps.realtime.sse import sse_format, sse_publish, sse_replay, sse_stream

FLUX_URL = "/api/v1/staff/dons/flux/"
IN_MEMORY = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


@pytest.fixture(autouse=True)
def _memory(settings):
    settings.CHANNEL_LAYERS = IN_MEMORY
    cache.clear()
    yield
    cache.clear()


async def _take(stream, count: int) -> list[str]:
    chunks = []
    async for chunk in stream:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        if len(chunks) == count:
            break
    await stream.aclose()
    return chunks


# --- Format et reprise ------------------------------------------------------------------------------


def test_format_is_one_json_line():
    assert sse_format(event="dons.operation", data={"a": "é"}, event_id=7) == (
        'id: 7\nevent: dons.operation\ndata: {"a":"é"}\n\n'
    )


def test_replay_after_last_event_id():
    for i in range(3):
        sse_publish(stream="t", event="e", data={"n": i})

    records, gap = sse_replay(stream="t", last_event_id="1")

    assert [r["id"] for r in records] == [2, 3]
    assert gap is False
    assert sse_replay(stream="t", last_event_id=None) == ([], False)
    assert sse_replay(stream="t", last_event_id="3") == ([], False)


def test_replay_detects_gaps(settings):
    settings.SSE_REPLAY_SIZE = 2
    for i in range(5):
        sse_publish(stream="t", event="e", data={"n": i})

    assert sse_replay(stream="t", last_event_id="1") == ([], True)  # trou trop grand
    assert sse_replay(stream="t", last_event_id="99")[1] is True  # numéro inconnu (cache vidé)
    assert sse_replay(stream="t", last_event_id="abc")[1] is True
    cache.delete("sse:evt:t:5")  # événement expiré
    assert sse_replay(stream="t", last_event_id="3")[1] is True


# --- Générateur ------------------------------------------------------------------------------------------


def test_stream_sends_retry_then_live_events_then_heartbeat():
    async def scenario():
        stream = sse_stream(stream="live", heartbeat=0.05)
        first = await stream.__anext__()
        await sync_to_async(sse_publish)(stream="live", event="dons.operation", data={"id": "d1"})
        event = await stream.__anext__()
        ping = await stream.__anext__()
        await stream.aclose()
        return first, event, ping

    first, event, ping = asyncio.run(scenario())

    assert first.startswith("retry: 5000\n")
    assert event == 'id: 1\nevent: dons.operation\ndata: {"id":"d1"}\n\n'
    assert ping == ": ping\n\n"


def test_stream_replays_missed_events_and_resyncs_on_gap(settings):
    sse_publish(stream="r", event="dons.operation", data={"n": 1})
    sse_publish(stream="r", event="dons.operation", data={"n": 2})

    chunks = asyncio.run(_take(sse_stream(stream="r", last_event_id="1", heartbeat=5), 2))
    assert chunks[1] == 'id: 2\nevent: dons.operation\ndata: {"n":2}\n\n'

    settings.SSE_REPLAY_SIZE = 0
    resync = asyncio.run(
        _take(
            sse_stream(
                stream="r", last_event_id="0", heartbeat=5, resync=lambda: ("dons.synthese_invalidee", {"resync": True})
            ),
            2,
        )
    )
    assert resync[1] == 'id: 2\nevent: dons.synthese_invalidee\ndata: {"resync":true}\n\n'


def test_stream_ends_after_max_duration():
    chunks = asyncio.run(_take(sse_stream(stream="m", heartbeat=0.01, max_seconds=0.03), 50))

    assert chunks[0].startswith("retry:")
    assert 1 <= len(chunks) < 50


# --- Événements des dons (branchement on_commit, sans toucher aux services) ----------------------


@pytest.fixture
def published(monkeypatch):
    calls: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        realtime_dons, "sse_publish", lambda *, stream, event, data: calls.append((stream, event, data)) or 1
    )
    return calls


def test_cash_collection_entry_and_validation_emit_events(world, fund, published, django_capture_on_commit_callbacks):  # noqa: F811
    sd, dakar = f"dons.{world.sd.pk}", f"dons.{world.dakar.pk}"

    with django_capture_on_commit_callbacks(execute=True):
        collection = dons_services.cash_collection_create(
            actor=world.secretaire, node=world.sd, fund=fund, mass_date=datetime.date(2026, 9, 27),
            mass_label="Messe de 10 h", amount=184_500, counter_one="Cécile Coly", counter_two="Jean Mendy",
        )  # fmt: skip

    assert [(s, e) for s, e, _ in published] == [
        (sd, "dons.operation"),
        (sd, "dons.synthese_invalidee"),
        (dakar, "dons.synthese_invalidee"),
    ]
    assert published[0][2]["kind"] == "quete" and published[0][2]["status"] == "saisie"
    assert published[2][2] == {"node_id": str(world.dakar.pk), "month": "2026-09"}

    published.clear()
    with django_capture_on_commit_callbacks(execute=True):
        dons_services.cash_collection_validate(collection=collection, actor=world.cure)

    operation = published[0][2]
    assert (published[0][0], published[0][1]) == (sd, "dons.operation")
    assert operation["kind"] == "don" and operation["status"] == "confirme" and operation["channel"] == "especes"
    for _, _, data in published:
        assert not {"amount", "net_amount", "donor", "donor_name", "counter_one"} & set(data)


def test_online_donation_confirmation_emits_once(world, fund, published, django_capture_on_commit_callbacks):  # noqa: F811
    donation, _, _ = dons_services.checkout_create(fund=fund, amount=5000, fees_covered=False, anonymous=False)
    assert published == []  # « en attente » : rien à montrer

    with django_capture_on_commit_callbacks(execute=True):
        dons_services.donation_transition(donation=donation, to=DonationStatus.CONFIRME, source=StatusSource.WEBHOOK)

    assert [e for _, e, _ in published].count("dons.operation") == 1
    assert published[0][2]["status"] == "confirme"


def test_nothing_is_published_on_rollback(world, fund, published):  # noqa: F811
    donation, _, _ = dons_services.checkout_create(fund=fund, amount=5000, fees_covered=False, anonymous=False)

    dons_services.donation_transition(donation=donation, to=DonationStatus.CONFIRME, source=StatusSource.WEBHOOK)

    assert published == []  # la transaction du test n'est jamais validée


# --- Vue : authentification, droits, réponse ------------------------------------------------------


def _get(user=None, **params):
    client = APIClient()
    if user is not None:
        params["ticket"] = ws_ticket_issue(user=user)
    return client.get(FLUX_URL, params, HTTP_ACCEPT="text/event-stream")


def test_view_requires_authentication(world):  # noqa: F811
    response = APIClient().get(FLUX_URL, {"noeud": str(world.sd.pk)}, HTTP_ACCEPT="text/event-stream")

    assert response.status_code == 401


def test_view_rejects_a_spent_ticket(world):  # noqa: F811
    ticket = ws_ticket_issue(user=world.cure)
    client = APIClient()
    assert client.get(FLUX_URL, {"noeud": str(world.sd.pk), "ticket": ticket}).status_code == 200
    assert client.get(FLUX_URL, {"noeud": str(world.sd.pk), "ticket": ticket}).status_code == 401


def test_view_requires_parish_capability(world):  # noqa: F811
    assert _get(world.fidele, noeud=str(world.sd.pk)).status_code == 403
    assert _get(world.autre_cure, noeud=str(world.sd.pk)).status_code == 403
    # Un droit hérité (doyen) ne donne pas le flux détaillé d'une paroisse.
    assert _get(world.doyen, noeud=str(world.sd.pk)).status_code == 403


def test_view_diocese_stream_for_diocesan_roles(world):  # noqa: F811
    assert _get(world.econome_dio, noeud=str(world.dakar.pk)).status_code == 200
    assert _get(world.cure, noeud=str(world.dakar.pk)).status_code == 403
    assert _get(world.cure, noeud=str(world.tree.doyenne.pk)).status_code == 400


def test_view_streams_events(world):  # noqa: F811
    response = _get(world.cure, noeud=str(world.sd.pk))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")
    assert response["Cache-Control"] == "no-cache, no-transform"
    assert response["X-Accel-Buffering"] == "no"

    async def scenario():
        stream = response.streaming_content
        first = await stream.__anext__()
        await sync_to_async(sse_publish)(stream=f"dons.{world.sd.pk}", event="dons.synthese_invalidee", data={"n": 1})
        second = await stream.__anext__()
        await stream.aclose()
        return first.decode(), second.decode()

    first, second = asyncio.run(scenario())
    assert first.startswith("retry: ")
    assert "event: dons.synthese_invalidee" in second
