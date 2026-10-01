"""Reprise des encodages interrompus (worker média tué par un redéploiement, tâche perdue)."""

import datetime

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.audio import services
from apps.audio.enums import TrackStatus
from apps.audio.models import Track
from apps.audio.tasks import audio_transcode_task
from apps.audio.tests.conftest import ready_track
from apps.messaging.models import Notification

pytestmark = pytest.mark.django_db


@pytest.fixture
def queued(monkeypatch):
    calls = []
    monkeypatch.setattr(audio_transcode_task, "delay", lambda *args: calls.append(args))
    return calls


def _stuck(world, *, status=TrackStatus.ENCODAGE, minutes=60, attempts=1):
    track = ready_track(world.chorale, "Homélie : le bon Samaritain", uploaded_by=world.cure)
    ago = timezone.now() - datetime.timedelta(minutes=minutes)
    Track.objects.filter(pk=track.pk).update(
        status=status, encoding_started_at=ago, updated_at=ago, encode_attempts=attempts,
        encoding_step="forme_onde", encoding_percent=90,
    )  # fmt: skip
    return track


def test_an_interrupted_encoding_is_requeued(world, queued, django_capture_on_commit_callbacks):
    track = _stuck(world)

    with django_capture_on_commit_callbacks(execute=True):
        result = services.tracks_stalled_requeue()

    assert result == {"relancees": 1, "echecs": 0}
    track.refresh_from_db()
    assert (track.status, track.encoding_percent) == (TrackStatus.EN_FILE, 0)
    assert queued == [(str(track.pk), track.version)]


def test_a_lost_queued_task_is_requeued(world, queued, django_capture_on_commit_callbacks):
    _stuck(world, status=TrackStatus.EN_FILE)

    with django_capture_on_commit_callbacks(execute=True):
        assert services.tracks_stalled_requeue()["relancees"] == 1
    assert len(queued) == 1


def test_a_recent_or_locked_encoding_is_left_alone(world, queued, django_capture_on_commit_callbacks):
    _stuck(world, minutes=10)  # encore dans les délais
    locked = _stuck(world)
    cache.set(services._lock_key(locked.pk), "worker-vivant", 60)

    with django_capture_on_commit_callbacks(execute=True):
        assert services.tracks_stalled_requeue() == {"relancees": 0, "echecs": 0}
    assert queued == []


def test_an_encoding_interrupted_again_and_again_fails_and_warns_the_uploader(world, queued):
    track = _stuck(world, attempts=4)

    assert services.tracks_stalled_requeue() == {"relancees": 0, "echecs": 1}
    track.refresh_from_db()
    assert track.status == TrackStatus.ECHEC and "à répétition" in track.failure_reason
    assert Notification.objects.filter(user=world.cure, event_type="audio.encodage_echec").exists()
    assert queued == []


def test_ready_tracks_are_never_touched(world, queued):
    ready_track(world.chorale, "Kyrie")
    assert services.tracks_stalled_requeue() == {"relancees": 0, "echecs": 0}


def test_the_watchdog_runs_every_quarter_hour(settings):
    entry = settings.CELERY_BEAT_SCHEDULE["audio_transcode_stalled"]
    assert entry["task"] == "apps.audio.tasks.audio_transcode_stalled_task"
    assert entry["schedule"].minute == {0, 15, 30, 45}
