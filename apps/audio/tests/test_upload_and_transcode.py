"""Upload (POST présigné / local) puis encodage réel par ffmpeg d'un fichier de 3 s."""

import json
import os

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audio import services, storage, transcode
from apps.audio.enums import TrackStatus
from apps.audio.models import Track, TrackRendition
from apps.audio.tasks import audio_transcode_task
from apps.audio.tests.conftest import client_for, sine_file
from apps.messaging.models import Notification

pytestmark = pytest.mark.django_db

UPLOADS = "/api/v1/audio/uploads/"


def _start(client, world, **overrides):
    body = {
        "source_id": str(world.chorale.pk),
        "album_id": str(world.messe.pk),
        "title": "Kyrie",
        "file_name": "kyrie.mp3",
        "file_type": "audio/mpeg",
        "file_size": 48_000,
        "rights_confirmed": True,
        **overrides,
    }
    return client.post(UPLOADS, body, format="json")


# --- Démarrage --------------------------------------------------------------------------------


def test_upload_start_requires_rights_checkbox(world):
    response = _start(client_for(world.cure), world, rights_confirmed=False)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "droits_non_confirmes"


@pytest.mark.parametrize(
    ("file_name", "file_type"),
    [("sermon.exe", "audio/mpeg"), ("kyrie.mp3", "text/html"), ("kyrie.wav", "audio/mpeg")],
)
def test_upload_start_rejects_unknown_or_inconsistent_types(world, file_name, file_type):
    response = _start(client_for(world.cure), world, file_name=file_name, file_type=file_type)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "format_audio"


def test_upload_start_rejects_files_over_500_mo(world):
    response = _start(client_for(world.cure), world, file_size=500 * 1024 * 1024 + 1)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "fichier_trop_gros"


def test_upload_start_needs_audio_publier_on_the_node(world):
    assert _start(client_for(world.fidele), world).status_code == 403
    assert _start(client_for(world.cure_st), world).status_code == 403  # curé d'une autre paroisse
    assert _start(client_for(), world).status_code in (401, 403)


def test_upload_start_local_gives_the_local_endpoint(world):
    response = _start(client_for(world.secretaire), world)
    assert response.status_code == 201, response.content
    data = response.json()
    track = Track.objects.get(pk=data["upload_id"])
    assert track.status == TrackStatus.BROUILLON
    assert track.rights_confirmed_at is not None
    assert track.raw_file.file.name.startswith("audio-raw/")
    assert data["url"].endswith(f"/api/v1/audio/uploads/{track.pk}/local/")
    assert data["max_size"] == 500 * 1024 * 1024
    assert data["track"]["status"] == "brouillon"


def test_upload_start_s3_returns_a_presigned_post(world, monkeypatch):
    calls = {}

    def fake_post(**kwargs):
        calls.update(kwargs)
        return {"url": "https://minio.local/jangubi", "fields": {"key": kwargs["key"], "policy": "p"}}

    monkeypatch.setattr(storage, "is_s3", lambda: True)
    monkeypatch.setattr(storage, "presigned_post", fake_post)
    response = _start(client_for(world.cure), world, file_name="gloria.m4a", file_type="audio/mp4")
    assert response.status_code == 201
    data = response.json()
    assert data["method"] == "POST" and data["url"] == "https://minio.local/jangubi"
    assert calls["key"].startswith("audio-raw/") and calls["key"].endswith(".m4a")
    assert calls["max_size"] == 500 * 1024 * 1024
    assert calls["content_type"] == "audio/mp4"


def test_finish_without_the_file_is_refused(world, media_root):
    data = _start(client_for(world.cure), world).json()
    response = client_for(world.cure).post(f"{UPLOADS}{data['upload_id']}/terminer/")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "upload_absent"


def test_other_users_cannot_finish_someone_elses_upload(world, media_root):
    data = _start(client_for(world.cure), world).json()
    response = client_for(world.fidele).post(f"{UPLOADS}{data['upload_id']}/terminer/")
    assert response.status_code == 404


# --- Parcours complet avec un vrai ffmpeg -------------------------------------------------------


def _upload_sine(world, tmp_path, *, user=None):
    user = user or world.cure
    client = client_for(user)
    src = sine_file(str(tmp_path / "kyrie.mp3"))
    data = _start(client, world, file_size=os.path.getsize(src)).json()
    with open(src, "rb") as fh:
        upload = SimpleUploadedFile("kyrie.mp3", fh.read(), content_type="audio/mpeg")
    response = client.post(f"{UPLOADS}{data['upload_id']}/local/", {"file": upload}, format="multipart")
    assert response.status_code == 200, response.content
    return client, data["upload_id"]


def test_full_upload_and_real_ffmpeg_encoding(world, tmp_path, media_root, django_capture_on_commit_callbacks):
    client, track_id = _upload_sine(world, tmp_path)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(f"{UPLOADS}{track_id}/terminer/")
    assert response.status_code == 202
    assert response.json()["status"] == "en_file"

    track = Track.objects.get(pk=track_id)
    assert track.status == TrackStatus.PRET, track.failure_reason
    assert track.version == 1 and track.encoded_version == 1
    assert 2.9 <= track.duration_seconds <= 3.2
    assert track.probe_tags.get("title") == "Kyrie de la messe"
    assert len(track.waveform) == 200 and max(track.waveform) == 1.0

    base = media_root / "audio-hls" / str(track.pk) / "1"
    master = (base / "master.m3u8").read_text()
    assert master.count("#EXT-X-STREAM-INF") == 3
    for folder in ("bas", "moyen", "haut"):
        playlist = (base / folder / "index.m3u8").read_text()
        assert "#EXT-X-TARGETDURATION" in playlist and "#EXT-X-ENDLIST" in playlist
        assert list((base / folder).glob("seg_*.ts"))
    assert (base / "audio.mp3").stat().st_size > 0
    assert json.loads((base / "waveform.json").read_text())["peaks"] == track.waveform

    kinds = dict(TrackRendition.objects.filter(track=track).values_list("kind", "bitrate_kbps"))
    low = 32 if transcode.has_encoder("libfdk_aac") else 48  # HE-AAC si disponible, sinon AAC-LC 48k
    assert kinds == {"hls_bas": low, "hls_moyen": 64, "hls_haut": 128, "mp3": 128}

    notification = Notification.objects.get(user=world.cure)
    assert notification.event_type == "audio.encodage_termine"
    assert notification.payload["track_id"] == str(track.pk)

    # Idempotence : une livraison en double ou une version périmée ne refait rien.
    assert services.transcode_track(track_id=track.pk, version=1) == "deja_fait"
    assert services.transcode_track(track_id=track.pk, version=0) == "perime"
    # Un second « terminer » ne relance pas d'encodage.
    assert client.post(f"{UPLOADS}{track_id}/terminer/").json()["version"] == 1


def test_loudness_is_normalised_to_minus_16_lufs(world, tmp_path, media_root, django_capture_on_commit_callbacks):
    import re
    import subprocess

    client, track_id = _upload_sine(world, tmp_path)
    with django_capture_on_commit_callbacks(execute=True):
        client.post(f"{UPLOADS}{track_id}/terminer/")
    mp3 = media_root / "audio-hls" / track_id / "1" / "audio.mp3"
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(mp3), "-af", "ebur128", "-f", "null", "-"],
        capture_output=True,
        check=True,
    ).stderr.decode()
    integrated = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", out)[-1])
    assert -19.0 <= integrated <= -13.0


def test_reencode_writes_a_new_immutable_version(world, tmp_path, media_root, django_capture_on_commit_callbacks):
    client, track_id = _upload_sine(world, tmp_path)
    with django_capture_on_commit_callbacks(execute=True):
        client.post(f"{UPLOADS}{track_id}/terminer/")
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(f"/api/v1/audio/pistes/{track_id}/reencoder/")
    assert response.status_code == 202
    track = Track.objects.get(pk=track_id)
    assert track.status == TrackStatus.PRET and track.encoded_version == 2
    assert (media_root / "audio-hls" / track_id / "1" / "master.m3u8").exists()  # l'ancienne reste servie en cache
    assert (media_root / "audio-hls" / track_id / "2" / "master.m3u8").exists()


def test_a_lock_prevents_two_workers_from_encoding_at_once(world, tmp_path, media_root):
    from django.core.cache import cache

    client, track_id = _upload_sine(world, tmp_path)
    Track.objects.filter(pk=track_id).update(status=TrackStatus.EN_FILE, version=1)
    cache.add(services._lock_key(track_id), "autre-worker", 60)
    assert services.transcode_track(track_id=track_id, version=1) == "verrouille"
    assert Track.objects.get(pk=track_id).status == TrackStatus.EN_FILE


def test_invalid_media_fails_immediately_with_a_reason(world, tmp_path, media_root, django_capture_on_commit_callbacks):
    client = client_for(world.cure)
    data = _start(client, world, file_size=20).json()
    bad = SimpleUploadedFile("kyrie.mp3", b"ceci n'est pas un son", content_type="audio/mpeg")
    client.post(f"{UPLOADS}{data['upload_id']}/local/", {"file": bad}, format="multipart")
    with django_capture_on_commit_callbacks(execute=True):
        client.post(f"{UPLOADS}{data['upload_id']}/terminer/")
    track = Track.objects.get(pk=data["upload_id"])
    assert track.status == TrackStatus.ECHEC
    assert "illisible" in track.failure_reason or "Aucune piste audio" in track.failure_reason
    assert track.encode_attempts == 1  # pas de nouvelle tentative pour un fichier invalide
    assert Notification.objects.get(user=world.cure).event_type == "audio.encodage_echec"
    status = client.get(f"{UPLOADS}{data['upload_id']}/").json()
    assert status["status"] == "echec" and status["failure_reason"]


def test_technical_errors_are_retried_three_times_then_fail(world, tmp_path, media_root, monkeypatch):
    client, track_id = _upload_sine(world, tmp_path)
    Track.objects.filter(pk=track_id).update(status=TrackStatus.EN_FILE, version=1)
    from django.utils import timezone

    from apps.files.models import File

    File.objects.filter(pk=Track.objects.get(pk=track_id).raw_file_id).update(upload_finished_at=timezone.now())

    def broken(*args, **kwargs):
        raise transcode.TranscodeError("disque plein")

    monkeypatch.setattr(transcode, "transcode", broken)

    # Tentative intermédiaire : l'erreur remonte (la tâche réessaiera), la piste revient en file.
    with pytest.raises(transcode.TranscodeError):
        services.transcode_track(track_id=track_id, version=1, final_attempt=False)
    assert Track.objects.get(pk=track_id).status == TrackStatus.EN_FILE

    # Par la tâche Celery : tant qu'il reste des tentatives, elle demande un nouvel essai…
    from celery.exceptions import Retry

    with pytest.raises(Retry):
        audio_transcode_task.apply(args=[track_id, 1], retries=0, throw=True)
    assert Track.objects.get(pk=track_id).status == TrackStatus.EN_FILE
    # … et à la 3e nouvelle tentative (4e essai), la piste passe en échec et l'uploader est prévenu.
    assert audio_transcode_task.apply(args=[track_id, 1], retries=3).get() == "echec"
    track = Track.objects.get(pk=track_id)
    assert track.status == TrackStatus.ECHEC and "disque plein" in track.failure_reason
    assert Notification.objects.filter(user=world.cure, event_type="audio.encodage_echec").exists()


def test_transcode_task_is_routed_to_the_media_queue(settings):
    assert audio_transcode_task.queue == "media"
    assert settings.CELERY_TASK_ROUTES["apps.audio.tasks.audio_transcode_task"] == {"queue": "media"}
    assert settings.CELERY_TASK_ROUTES["apps.audio.tasks.audio_reco_recompute_task"] == {"queue": "reco"}
