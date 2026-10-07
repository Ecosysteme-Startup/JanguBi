"""Événements d'écoute (table partitionnée, idempotence) et recommandations précalculées."""

import datetime
import uuid

import pytest
from django.db import connection
from django.utils import timezone

from apps.audio import recommendations, services
from apps.audio.enums import LiturgicalSeason, NeighborMethod
from apps.audio.models import Like, PlayEvent, TrackNeighbor, UserRecommendation
from apps.audio.tasks import audio_play_event_partitions_task, audio_reco_recompute_task
from apps.audio.tests.conftest import client_for, ready_track
from apps.hierarchy.tests.factories import person

pytestmark = pytest.mark.django_db

API = "/api/v1/audio"


def _event(track, kind="start", *, at=None, position=0.0, event_id=None):
    return {
        "client_event_id": str(event_id or uuid.uuid4()),
        "track_id": str(track.pk),
        "kind": kind,
        "occurred_at": (at or timezone.now()).isoformat(),
        "position_seconds": position,
        "device_id": "android-mt",
    }


# --- Événements ------------------------------------------------------------------------------


def test_events_batch_is_idempotent_and_counts_starts(world):
    kyrie = ready_track(world.chorale, "Kyrie")
    homelie = ready_track(world.paroisse, "Homélie", album=world.homelies)
    start = _event(kyrie, "start")
    batch = {
        "events": [
            start,
            _event(kyrie, "progress", position=120),
            _event(kyrie, "complete", position=240),
            _event(homelie, "start"),  # non autorisée pour Awa : rejetée
            _event(kyrie, "start", at=timezone.now() - datetime.timedelta(days=30)),  # trop ancienne
            _event(kyrie, "start", at=timezone.now() + datetime.timedelta(hours=2)),  # dans le futur
        ]
    }
    response = client_for(world.autre).post(f"{API}/evenements/", batch, format="json")
    assert response.status_code == 202
    assert response.json() == {"recus": 6, "enregistres": 3, "doublons": 0, "rejetes": 3}
    kyrie.refresh_from_db()
    assert kyrie.play_count == 1

    # Reprise réseau : le même lot renvoyé ne compte pas deux fois.
    again = client_for(world.autre).post(f"{API}/evenements/", {"events": [start]}, format="json").json()
    assert again == {"recus": 1, "enregistres": 0, "doublons": 1, "rejetes": 0}
    kyrie.refresh_from_db()
    assert kyrie.play_count == 1
    assert PlayEvent.objects.filter(track=kyrie, user=world.autre).count() == 3


def test_anonymous_events_are_kept_without_user(world):
    kyrie = ready_track(world.chorale, "Kyrie")
    assert (
        client_for().post(f"{API}/evenements/", {"events": [_event(kyrie)]}, format="json").json()["enregistres"] == 1
    )
    assert PlayEvent.objects.get(track=kyrie).user_id is None


def test_events_batch_is_limited(world):
    kyrie = ready_track(world.chorale, "Kyrie")
    response = client_for(world.fidele).post(
        f"{API}/evenements/", {"events": [_event(kyrie) for _ in range(101)]}, format="json"
    )
    assert response.status_code == 400


def _partitions() -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
            "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'audio_play_event'"
        )
        return {r[0] for r in cursor.fetchall()}


def test_play_event_table_is_partitioned_by_month():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT partstrat FROM pg_partitioned_table pt JOIN pg_class c ON c.oid = pt.partrelid WHERE c.relname = 'audio_play_event'"
        )
        assert cursor.fetchone() == ("r",)
    assert "audio_play_event_default" in _partitions()


def test_monthly_partition_task_creates_ahead_moves_default_rows_and_purges(world):
    kyrie = ready_track(world.chorale, "Kyrie")
    in_2027 = datetime.datetime(2027, 3, 14, 9, 0, tzinfo=datetime.UTC)
    old = datetime.datetime(2025, 6, 1, 9, 0, tzinfo=datetime.UTC)
    with connection.cursor() as cursor:
        for at in (in_2027, old):
            cursor.execute(
                "INSERT INTO audio_play_event (occurred_at, received_at, client_event_id, track_id, kind) "
                "VALUES (%s, now(), %s, %s, 'start')",
                [at, str(uuid.uuid4()), str(kyrie.pk)],
            )
        cursor.execute(
            "CREATE TABLE audio_play_event_p202507 PARTITION OF audio_play_event FOR VALUES FROM ('2025-07-01') TO ('2025-08-01')"
        )

    result = services.play_event_partitions_ensure(today=datetime.date(2027, 2, 10))
    assert result["creees"] == ["audio_play_event_p202702", "audio_play_event_p202703", "audio_play_event_p202704"]
    assert "audio_play_event_p202507" in result["supprimees"]  # plus de 13 mois
    assert {"audio_play_event_p202703", "audio_play_event_default"} <= _partitions()
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM audio_play_event_p202703")
        assert cursor.fetchone() == (1,)  # déplacée depuis la partition par défaut
        cursor.execute("SELECT count(*) FROM audio_play_event_default")
        assert cursor.fetchone() == (0,)  # l'événement de 2025 est purgé
    # Idempotente.
    assert services.play_event_partitions_ensure(today=datetime.date(2027, 2, 10))["creees"] == []
    assert isinstance(audio_play_event_partitions_task.apply().get(), dict)


# --- Recommandations -------------------------------------------------------------------------


def _listen(user, track, *, days_ago=1, kind="complete"):
    at = timezone.now() - datetime.timedelta(days=days_ago)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO audio_play_event (occurred_at, received_at, client_event_id, user_id, track_id, kind, "
            "position_seconds) VALUES (%s, now(), %s, %s, %s, %s, 240)",
            [at, str(uuid.uuid4()), user.pk, str(track.pk), kind],
        )


@pytest.fixture
def listening(world, settings):
    settings.AUDIO_RECO_MIN_CO_LISTENERS = 2
    w = world
    w.kyrie = ready_track(w.chorale, "Kyrie", album=w.messe)
    w.gloria = ready_track(w.chorale, "Gloria", album=w.messe)
    w.sanctus = ready_track(w.chorale, "Sanctus", album=w.messe)
    w.homelie = ready_track(w.paroisse, "Homélie du 27 septembre", album=w.homelies)
    w.neuve = ready_track(w.chorale, "Ave Maria (nouveau)")
    w.listeners = [person(f"auditeur{i}@test.sn", paroisse_suivie=w.sd) for i in range(3)]
    for u in w.listeners:
        _listen(u, w.kyrie)
        _listen(u, w.gloria)
    _listen(w.listeners[0], w.sanctus)
    _listen(w.listeners[1], w.sanctus)
    # Marie-Thérèse a écouté le Kyrie en entier et passé l'Homélie.
    _listen(w.fidele, w.kyrie)
    _listen(w.fidele, w.homelie, kind="skip")
    return w


def test_colisten_neighbors_use_cosine_on_90_days(listening):
    w = listening
    old = person("ancien@test.sn")
    _listen(old, w.kyrie, days_ago=120)  # hors fenêtre
    _listen(old, w.neuve, days_ago=120)
    assert recommendations.colisten_neighbors_compute() > 0
    neighbors = dict(
        TrackNeighbor.objects.filter(track=w.kyrie, method=NeighborMethod.COECOUTE).values_list(
            "neighbor__title", "score"
        )
    )
    # Kyrie : 4 auditeurs ; Gloria : 3, tous communs → 3 / sqrt(4 × 3).
    assert neighbors["Gloria"] == pytest.approx(3 / (4 * 3) ** 0.5)
    assert neighbors["Sanctus"] == pytest.approx(2 / (4 * 2) ** 0.5)
    assert "Ave Maria (nouveau)" not in neighbors
    assert neighbors["Gloria"] > neighbors["Sanctus"]


def test_content_neighbors_come_from_metadata(listening):
    assert recommendations.content_neighbors_compute() > 0
    near = dict(
        TrackNeighbor.objects.filter(track=listening.neuve, method=NeighborMethod.CONTENU).values_list(
            "neighbor__title", "score"
        )
    )
    # Piste neuve sans album : rattachée aux chants de sa chorale, pas à l'homélie de la paroisse.
    assert set(near) == {"Kyrie", "Gloria", "Sanctus"}


def test_content_neighbors_rank_same_album_first(listening):
    w = listening
    recommendations.content_neighbors_compute()
    near = list(
        TrackNeighbor.objects.filter(track=w.kyrie, method=NeighborMethod.CONTENU)
        .order_by("-score")
        .values_list("neighbor__title", flat=True)
    )
    # Même album (et même chorale) avant la simple même chorale ; jamais l'homélie.
    assert set(near[:2]) == {"Gloria", "Sanctus"}
    assert near[2] == "Ave Maria (nouveau)"
    assert "Homélie du 27 septembre" not in near


def test_content_neighbors_use_shared_tags_across_sources(listening):
    w = listening
    marial = ready_track(w.paroisse, "Je vous salue Marie", tags=["marie", "chapelet"])
    w.neuve.tags = ["marie", "chapelet"]
    w.neuve.save(update_fields=["tags"])

    recommendations.content_neighbors_compute()

    assert TrackNeighbor.objects.filter(track=w.neuve, neighbor=marial, method=NeighborMethod.CONTENU).exists()


def test_nightly_task_builds_user_recommendations_with_reasons(listening):
    w = listening
    result = audio_reco_recompute_task.apply().get()
    assert result["voisins_coecoute"] > 0 and result["recommandations"] > 0

    recos = {r.track.title: r for r in UserRecommendation.objects.filter(user=w.fidele).select_related("track")}
    assert "Kyrie" not in recos  # déjà écouté
    assert "Homélie du 27 septembre" not in recos  # passée
    assert recos["Gloria"].reason == "Parce que vous avez écouté « Kyrie »"
    assert recos["Gloria"].score > recos["Sanctus"].score
    assert len(recos) <= 100

    data = client_for(w.fidele).get(f"{API}/pour-vous/").json()
    assert data["personnalise"] is True and data["demarrage_a_froid"] is False
    assert data["results"][0]["track"]["title"] == "Gloria"
    assert data["results"][0]["reason"] == "Parce que vous avez écouté « Kyrie »"


def test_recommendations_never_leak_tracks_the_user_cannot_hear(listening):
    w = listening
    for u in w.listeners:
        _listen(u, w.homelie)
    _listen(w.autre, w.kyrie)
    recommendations.recompute_all()
    titles = set(UserRecommendation.objects.filter(user=w.autre).values_list("track__title", flat=True))
    assert "Homélie du 27 septembre" not in titles  # réservée aux membres de Saint-Dominique


def test_cold_start_uses_parish_news_editorial_playlists_then_season(world, monkeypatch):
    ready_track(world.chorale, "Kyrie", album=world.messe)
    ready_track(world.source_st, "Chant de l'Avent", liturgical_season=LiturgicalSeason.AVENT)
    monkeypatch.setattr(recommendations, "current_season", lambda day=None: LiturgicalSeason.AVENT)
    from apps.audio import selectors

    monkeypatch.setattr(selectors, "current_season", lambda day=None: LiturgicalSeason.AVENT)
    data = client_for(world.fidele).get(f"{API}/pour-vous/").json()
    assert data["demarrage_a_froid"] is True
    assert [(r["track"]["title"], r["reason"]) for r in data["results"]] == [
        ("Kyrie", "Nouveauté de Chorale Sainte-Cécile"),
        ("Chant de l'Avent", "Pour le temps de l'Avent"),
    ]


def test_recommendations_can_be_disabled_per_user_and_globally(listening, settings):
    w = listening
    recommendations.recompute_all()
    assert UserRecommendation.objects.filter(user=w.fidele).exists()
    client = client_for(w.fidele)
    assert client.put(f"{API}/reglages/", {"recommendations_enabled": False}, format="json").json() == {
        "recommendations_enabled": False
    }
    assert not UserRecommendation.objects.filter(user=w.fidele).exists()
    assert client.get(f"{API}/pour-vous/").json()["personnalise"] is False
    recommendations.recompute_all()
    assert not UserRecommendation.objects.filter(user=w.fidele).exists()

    settings.AUDIO_RECO_ENABLED = False
    assert audio_reco_recompute_task.apply().get() == {"desactive": True}


def test_next_tracks_follow_neighbors_then_album(listening):
    w = listening
    recommendations.colisten_neighbors_compute()
    titles = [t["title"] for t in client_for(w.fidele).get(f"{API}/pistes/{w.kyrie.pk}/ensuite/").json()]
    assert titles[:2] == ["Gloria", "Sanctus"]
    assert "Kyrie" not in titles
    # Piste sans voisin : suite de l'album.
    TrackNeighbor.objects.all().delete()
    titles = [t["title"] for t in client_for().get(f"{API}/pistes/{w.gloria.pk}/ensuite/").json()]
    assert "Homélie du 27 septembre" not in titles
    assert titles and "Gloria" not in titles


def test_likes_feed_the_colisten_matrix(listening):
    w = listening
    for u in w.listeners[:2]:
        Like.objects.create(user=u, track=w.neuve)
    recommendations.colisten_neighbors_compute()
    assert TrackNeighbor.objects.filter(track=w.neuve, neighbor=w.kyrie, method=NeighborMethod.COECOUTE).exists()
