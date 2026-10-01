"""Signalement d'une source (``POST audio/sources/<id>/signaler/``) et flux SSE de la progression
d'encodage (``GET audio/uploads/<id>/flux/``), en plus du polling de ``GET audio/uploads/<id>/``."""

import asyncio
import os

import pytest
from asgiref.sync import sync_to_async
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audio import services
from apps.audio.enums import TrackStatus
from apps.audio.models import Track, TrackReport
from apps.audio.tests.conftest import client_for, ready_track, sine_file
from apps.authentication.ws_tickets import ws_ticket_issue
from apps.realtime import audio as realtime_audio
from apps.realtime.sse import sse_publish

pytestmark = pytest.mark.django_db

API = "/api/v1/audio"
IN_MEMORY = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


# --- 1. Signalement d'une source -----------------------------------------------------------------


def test_source_report_is_listed_and_removal_deactivates_the_source(world):
    kyrie = ready_track(world.chorale, "Kyrie", album=world.messe)
    created = client_for(world.autre).post(
        f"{API}/sources/{world.chorale.pk}/signaler/", {"motif": "inapproprie", "comment": "Image"}, format="json"
    )
    assert created.status_code == 201, created.content
    report = created.json()
    assert report["cible"] == "source" and report["track"] is None and report["album"] is None
    assert report["source"]["id"] == str(world.chorale.pk) and report["motif"] == "inapproprie"

    listed = client_for(world.cure).get(f"{API}/moderation/signalements/").json()
    assert [(r["id"], r["cible"]) for r in listed] == [(report["id"], "source")]
    assert client_for(world.cure_st).get(f"{API}/moderation/signalements/").json() == []
    assert (
        client_for(world.cure_st)
        .post(f"{API}/moderation/signalements/{report['id']}/traiter/", {"resolution": "retire"}, format="json")
        .status_code
        == 403
    )

    done = client_for(world.cure).post(
        f"{API}/moderation/signalements/{report['id']}/traiter/", {"resolution": "retire"}, format="json"
    )
    assert done.status_code == 200 and done.json()["status"] == "retire"
    world.chorale.refresh_from_db()
    assert world.chorale.hidden_at is not None and world.chorale.is_active is False
    assert client_for(world.fidele).post(f"{API}/pistes/{kyrie.pk}/lecture/").status_code == 404
    assert str(world.chorale.pk) not in {s["id"] for s in client_for().get(f"{API}/sources/").json()}
    # Une source inactive n'est plus signalable.
    assert (
        client_for(world.autre)
        .post(f"{API}/sources/{world.chorale.pk}/signaler/", {"motif": "autre"}, format="json")
        .status_code
        == 404
    )

    # Seul audio.moderer rétablit une source retirée par la modération.
    refused = client_for(world.secretaire).patch(
        f"{API}/sources/{world.chorale.pk}/", {"is_active": True}, format="json"
    )
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "source_retiree"
    restored = client_for(world.cure).patch(f"{API}/sources/{world.chorale.pk}/", {"is_active": True}, format="json")
    assert restored.status_code == 200 and restored.json()["is_active"] is True
    world.chorale.refresh_from_db()
    assert world.chorale.hidden_at is None


def test_source_report_rejection_and_validation(world):
    url = f"{API}/sources/{world.paroisse.pk}/signaler/"
    assert client_for().post(url, {"motif": "autre"}, format="json").status_code in (401, 403)
    assert client_for(world.fidele).post(url, {"motif": "inconnu"}, format="json").status_code == 400
    assert (
        client_for(world.fidele)
        .post(f"{API}/sources/{world.messe.pk}/signaler/", {"motif": "autre"}, format="json")
        .status_code
        == 404
    )

    first = client_for(world.fidele).post(url, {"motif": "droits"}, format="json").json()
    client_for(world.autre).post(url, {"motif": "autre"}, format="json")
    done = client_for(world.cure).post(
        f"{API}/moderation/signalements/{first['id']}/traiter/", {"resolution": "rejete"}, format="json"
    )
    assert done.status_code == 200
    # Tous les signalements ouverts de la même source sont clos ensemble ; la source reste active.
    assert set(TrackReport.objects.filter(source=world.paroisse).values_list("status", flat=True)) == {"rejete"}
    world.paroisse.refresh_from_db()
    assert world.paroisse.is_active and world.paroisse.hidden_at is None


# --- 2. Flux SSE de la progression d'encodage ----------------------------------------------------


@pytest.fixture
def memory_layer(settings):
    settings.CHANNEL_LAYERS = IN_MEMORY
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def published(monkeypatch):
    calls: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        realtime_audio, "sse_publish", lambda *, stream, event, data: calls.append((stream, event, data)) or 1
    )
    return calls


def _upload(world, tmp_path, user):
    client = client_for(user)
    src = sine_file(str(tmp_path / "kyrie.mp3"))
    data = client.post(
        f"{API}/uploads/",
        {
            "source_id": str(world.chorale.pk), "album_id": str(world.messe.pk), "title": "Kyrie",
            "file_name": "kyrie.mp3", "file_type": "audio/mpeg", "file_size": os.path.getsize(src),
            "rights_confirmed": True,
        },
        format="json",
    ).json()  # fmt: skip
    with open(src, "rb") as fh:
        upload = SimpleUploadedFile("kyrie.mp3", fh.read(), content_type="audio/mpeg")
    assert (
        client.post(f"{API}/uploads/{data['upload_id']}/local/", {"file": upload}, format="multipart").status_code
        == 200
    )
    return client, data["upload_id"]


def test_encoding_publishes_each_step_until_ready(
    world, tmp_path, media_root, published, django_capture_on_commit_callbacks
):
    client, track_id = _upload(world, tmp_path, world.secretaire)
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(f"{API}/uploads/{track_id}/terminer/").status_code == 202

    streams = {s for s, _, _ in published}
    assert streams == {f"audio.upload.{track_id}"}
    assert {e for _, e, _ in published} == {"audio.encodage"}
    statuses = [d["status"] for _, _, d in published]
    assert statuses[0] == "en_file" and statuses[-1] == "pret"
    assert "encodage" in statuses
    steps = [d["encoding_step"] for _, _, d in published if d["status"] == "encodage"]
    assert steps[0] == "analyse" and "normalisation" in steps and "forme_onde" in steps
    percents = [d["encoding_percent"] for _, _, d in published if d["status"] == "encodage"]
    assert percents == sorted(percents) and all(0 <= p <= 100 for p in percents)
    last = published[-1][2]
    assert last == {
        "track_id": track_id, "version": 1, "status": "pret", "encoding_step": "termine", "encoding_percent": 100,
        "failure_reason": "", "final": True,
    }  # fmt: skip
    for _, _, data in published:
        assert "title" not in data and "Kyrie" not in str(data)


def test_failure_is_published_as_final(world, published, django_capture_on_commit_callbacks):
    track = Track.objects.create(source=world.chorale, title="Vide", status=TrackStatus.EN_FILE, version=1)
    with django_capture_on_commit_callbacks(execute=True):
        assert services.transcode_track(track_id=track.pk, version=1) == "echec"

    assert published[-1][2]["status"] == "echec" and published[-1][2]["final"] is True
    assert published[-1][2]["failure_reason"] == "Fichier source absent."


def test_nothing_is_published_on_rollback(world, tmp_path, media_root, published):
    client, track_id = _upload(world, tmp_path, world.secretaire)
    services.upload_finish(actor=world.secretaire, track=Track.objects.get(pk=track_id))
    assert published == []  # la transaction du test n'est jamais validée


def _flux(user, track_id, **headers):
    client = client_for()
    params = {"ticket": ws_ticket_issue(user=user)} if user is not None else {}
    return client.get(f"{API}/uploads/{track_id}/flux/", params, HTTP_ACCEPT="text/event-stream", **headers)


def test_flux_requires_authentication(world, memory_layer):
    track = Track.objects.create(source=world.chorale, title="Gloria", status=TrackStatus.ENCODAGE, version=1)
    assert _flux(None, track.pk).status_code == 401


def test_flux_rights_follow_the_upload_detail(world, memory_layer):
    track = Track.objects.create(
        source=world.chorale, title="Gloria", status=TrackStatus.ENCODAGE, version=1, uploaded_by=world.secretaire
    )
    assert _flux(world.fidele, track.pk).status_code == 403
    assert _flux(world.cure_st, track.pk).status_code == 403
    assert _flux(world.cure, track.pk).status_code == 200  # audio.publier sur la paroisse
    assert _flux(world.secretaire, track.pk).status_code == 200  # l'auteur de l'envoi
    assert _flux(world.cure, "00000000-0000-0000-0000-000000000000").status_code == 404


def test_flux_sends_current_state_then_live_progress(world, memory_layer):
    track = Track.objects.create(
        source=world.chorale, title="Gloria", status=TrackStatus.ENCODAGE, version=2,
        encoding_step="normalisation", encoding_percent=25, uploaded_by=world.secretaire,
    )  # fmt: skip
    response = _flux(world.secretaire, track.pk)
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")
    assert response["Cache-Control"] == "no-cache, no-transform"

    async def scenario():
        stream = response.streaming_content
        chunks = [await stream.__anext__(), await stream.__anext__()]
        await sync_to_async(realtime_audio.upload_progress_publish)(
            track_id=track.pk, version=2, status="encodage", step="qualites", percent=50
        )
        chunks.append(await stream.__anext__())
        await sync_to_async(realtime_audio.upload_progress_publish)(
            track_id=track.pk, version=2, status="pret", step="termine", percent=100
        )
        chunks.append(await stream.__anext__())
        rest = [c async for c in stream]  # le serveur ferme après l'événement final
        return [c.decode() if isinstance(c, bytes) else c for c in chunks], rest

    chunks, rest = asyncio.run(scenario())
    assert chunks[0].startswith("retry: ")
    assert chunks[1].startswith("event: audio.encodage\n")  # état courant, sans id
    assert '"encoding_step":"normalisation"' in chunks[1] and '"final":false' in chunks[1]
    assert chunks[2].startswith("id: 1\nevent: audio.encodage\n") and '"encoding_percent":50' in chunks[2]
    assert '"status":"pret"' in chunks[3] and '"final":true' in chunks[3]
    assert rest == []


def test_flux_of_a_finished_upload_sends_the_state_and_closes(world, memory_layer):
    track = Track.objects.create(
        source=world.chorale, title="Gloria", status=TrackStatus.PRET, version=1,
        encoding_step="termine", encoding_percent=100, uploaded_by=world.secretaire,
    )  # fmt: skip

    async def collect(response):
        return [c.decode() if isinstance(c, bytes) else c async for c in response.streaming_content]

    chunks = asyncio.run(collect(_flux(world.secretaire, track.pk, HTTP_LAST_EVENT_ID="3")))
    assert len(chunks) == 2 and '"final":true' in chunks[1]


def test_flux_resumes_from_last_event_id(world, memory_layer):
    track = Track.objects.create(
        source=world.chorale, title="Gloria", status=TrackStatus.ENCODAGE, version=1, uploaded_by=world.secretaire
    )
    stream = realtime_audio.stream_for(track.pk)
    sse_publish(stream=stream, event="audio.encodage", data={"encoding_percent": 10, "final": False})
    sse_publish(stream=stream, event="audio.encodage", data={"encoding_percent": 50, "final": False})
    response = _flux(world.secretaire, track.pk, HTTP_LAST_EVENT_ID="1")

    async def scenario():
        s = response.streaming_content
        chunks = [await s.__anext__(), await s.__anext__()]
        await s.aclose()
        return [c.decode() if isinstance(c, bytes) else c for c in chunks]

    chunks = asyncio.run(scenario())
    assert chunks[1] == 'id: 2\nevent: audio.encodage\ndata: {"encoding_percent":50,"final":false}\n\n'
