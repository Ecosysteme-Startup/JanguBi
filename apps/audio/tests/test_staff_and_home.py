"""Lot B3b : espace staff (albums, écoutes 30 jours), progression de l'encodage, pochettes,
accueil en un appel, signalement d'album, limite de débit des événements."""

import datetime
import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from apps.audio import selectors, services, storage
from apps.audio.enums import LiturgicalSeason, TrackStatus, Visibility
from apps.audio.models import Album, PlaybackPosition, Track
from apps.audio.tests.conftest import client_for, ready_track
from apps.audio.tests.test_upload_and_transcode import UPLOADS, _upload_sine
from apps.hierarchy.tests.factories import person

pytestmark = pytest.mark.django_db

API = "/api/v1/audio"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _play_event(track, *, days_ago: float, kind: str = "start") -> None:
    at = timezone.now() - datetime.timedelta(days=days_ago)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO audio_play_event (occurred_at, received_at, client_event_id, user_id, track_id, kind, "
            "position_seconds, device_id) VALUES (%s, %s, %s, NULL, %s, %s, 0, '')",
            [at, at, str(uuid.uuid4()), str(track.pk), kind],
        )


# --- 1. Espace staff -------------------------------------------------------------------------


def test_staff_albums_list_includes_drafts_of_my_sources_only(world):
    draft = Album.objects.create(source=world.chorale, title="Chants de la Toussaint (brouillon)")
    Album.objects.create(source=world.source_st, title="Messe à Sainte-Thérèse", published_at=timezone.now())
    ready_track(world.chorale, "Kyrie", album=world.messe)

    albums = client_for(world.secretaire).get(f"{API}/staff/albums/").json()
    assert {a["title"] for a in albums} == {
        "Chants de la Toussaint (brouillon)", "Messe du 27 septembre 2026", "Homélies du Père Emmanuel Tine",
    }  # fmt: skip
    by_title = {a["title"]: a for a in albums}
    assert by_title["Chants de la Toussaint (brouillon)"]["published_at"] is None
    assert by_title["Messe du 27 septembre 2026"]["track_count"] == 1

    only_chorale = client_for(world.secretaire).get(f"{API}/staff/albums/", {"source": str(world.chorale.pk)}).json()
    assert {a["id"] for a in only_chorale} == {str(draft.pk), str(world.messe.pk)}

    assert client_for(world.fidele).get(f"{API}/staff/albums/").json() == []
    assert client_for(world.fidele).get(f"{API}/staff/albums/", {"source": str(world.chorale.pk)}).status_code == 403
    assert client_for(world.cure_st).get(f"{API}/staff/albums/", {"source": str(world.chorale.pk)}).status_code == 403
    assert client_for().get(f"{API}/staff/albums/").status_code in (401, 403)


def test_staff_creates_and_edits_an_album(world):
    client = client_for(world.secretaire)
    created = client.post(
        f"{API}/staff/albums/",
        {"source_id": str(world.paroisse.pk), "kind": "retraite", "title": "Retraite de l'Avent",
         "visibility": "paroisse", "description": "Trois enseignements du Père Emmanuel Tine."},
        format="json",
    )  # fmt: skip
    assert created.status_code == 201, created.content
    album = created.json()
    assert album["published_at"] is None and album["visibility"] == "paroisse" and album["track_count"] == 0

    track = ready_track(world.paroisse, "Premier enseignement", album=Album.objects.get(pk=album["id"]))
    patched = client.patch(
        f"{API}/staff/albums/{album['id']}/", {"title": "Retraite de l'Avent 2026", "visibility": "public"}, format="json"
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Retraite de l'Avent 2026" and patched.json()["track_count"] == 1
    track.refresh_from_db()
    assert track.effective_visibility == Visibility.PUBLIC

    detail = client.get(f"{API}/staff/albums/{album['id']}/").json()
    assert [t["title"] for t in detail["tracks"]] == ["Premier enseignement"]
    assert detail["tracks"][0]["plays_30d"] == 0

    other = client_for(world.cure_st)
    assert other.patch(f"{API}/staff/albums/{album['id']}/", {"title": "x"}, format="json").status_code == 403
    assert other.get(f"{API}/staff/albums/{album['id']}/").status_code == 403
    assert other.post(
        f"{API}/staff/albums/", {"source_id": str(world.paroisse.pk), "title": "x"}, format="json"
    ).status_code == 403


def test_staff_tracks_show_plays_of_the_last_30_days_per_source(world):
    kyrie = ready_track(world.chorale, "Kyrie")
    gloria = ready_track(world.chorale, "Gloria")
    for days in (1, 2, 29):
        _play_event(kyrie, days_ago=days)
    _play_event(kyrie, days_ago=1, kind="complete")  # pas un début d'écoute
    _play_event(kyrie, days_ago=45)  # trop ancien
    tracks = client_for(world.secretaire).get(f"{API}/staff/pistes/", {"source": str(world.chorale.pk)}).json()
    plays = {t["title"]: t["plays_30d"] for t in tracks}
    assert plays == {"Kyrie": 3, "Gloria": 0}
    assert gloria.pk  # ordre par date de création, jamais par écoutes
    assert [t["title"] for t in tracks] == ["Gloria", "Kyrie"]
    # Aucune liste inter-sources : la source est obligatoire, et le curé d'ailleurs n'y a pas accès.
    assert client_for(world.secretaire).get(f"{API}/staff/pistes/").status_code == 400
    assert client_for(world.cure_st).get(f"{API}/staff/pistes/", {"source": str(world.chorale.pk)}).status_code == 403
    # Les fiches auditeur n'exposent aucun compteur.
    assert "plays_30d" not in client_for(world.fidele).get(f"{API}/pistes/{kyrie.pk}/").json()


# --- 2. Progression de l'encodage -------------------------------------------------------------


def test_encoding_progress_is_recorded_at_each_step(world, tmp_path, media_root, monkeypatch):
    client, track_id = _upload_sine(world, tmp_path)
    seen: list[tuple[str, int, str, int]] = []
    original = services._progress_recorder

    def spy(tid, version):
        record = original(tid, version)

        def wrapped(step, percent):
            record(step, percent)
            db = Track.objects.values_list("encoding_step", "encoding_percent").get(pk=tid)
            seen.append((step, percent, *db))

        return wrapped

    monkeypatch.setattr(services, "_progress_recorder", spy)
    monkeypatch.setattr("apps.audio.tasks.audio_transcode_task.delay", lambda *a, **k: None)
    queued = client.post(f"{UPLOADS}{track_id}/terminer/").json()
    assert (queued["status"], queued["encoding_step"], queued["encoding_percent"]) == ("en_file", "", 0)

    assert services.transcode_track(track_id=track_id, version=1) == "pret"
    steps = [s[0] for s in seen]
    assert steps[0] == "analyse" and steps[1] == "normalisation"
    assert steps.count("qualites") == 4  # 3 débits HLS puis le MP3
    assert steps[-2:] == ["forme_onde", "forme_onde"]  # forme d'onde, puis dépôt
    percents = [s[1] for s in seen]
    assert percents == sorted(percents) and percents[-1] == 90
    assert all((step, pct) == (db_step, db_pct) for step, pct, db_step, db_pct in seen)  # écrit tout de suite

    done = client.get(f"{UPLOADS}{track_id}/").json()
    assert (done["status"], done["encoding_step"], done["encoding_percent"]) == ("pret", "termine", 100)
    assert done["plays_30d"] is None  # compteur réservé aux listes staff

    listed = client.get(f"{API}/staff/pistes/", {"source": str(world.chorale.pk)}).json()
    assert listed[0]["encoding_step"] == "termine" and listed[0]["encoding_percent"] == 100


def test_progress_of_a_stale_version_is_ignored(world):
    track = ready_track(world.chorale, "Kyrie")
    Track.objects.filter(pk=track.pk).update(status=TrackStatus.ENCODAGE, version=2)
    services._progress_recorder(track.pk, 1)("qualites", 50)
    services._progress_recorder(track.pk, 2)("qualites", 250)
    track.refresh_from_db()
    assert (track.encoding_step, track.encoding_percent) == ("qualites", 100)


# --- 3. Pochette ---------------------------------------------------------------------------------


def _cover_start(client, album, **overrides):
    body = {"file_name": "messe.png", "file_type": "image/png", "file_size": len(PNG), **overrides}
    return client.post(f"{API}/staff/albums/{album.pk}/pochette/", body, format="json")


def test_cover_upload_local_then_finish(world, media_root):
    client = client_for(world.secretaire)
    start = _cover_start(client, world.messe)
    assert start.status_code == 201, start.content
    data = start.json()
    assert data["url"].endswith(f"/api/v1/audio/staff/albums/{world.messe.pk}/pochette/{data['file_id']}/local/")
    assert data["max_size"] == 5 * 1024 * 1024

    finish_url = f"{API}/staff/albums/{world.messe.pk}/pochette/terminer/"
    early = client.post(finish_url, {"file_id": data["file_id"]}, format="json")
    assert early.status_code == 400 and early.json()["error"]["code"] == "upload_absent"

    upload = SimpleUploadedFile("messe.png", PNG, content_type="image/png")
    local = f"{API}/staff/albums/{world.messe.pk}/pochette/{data['file_id']}/local/"
    assert client.post(local, {"file": upload}, format="multipart").status_code == 204

    done = client.post(finish_url, {"file_id": data["file_id"]}, format="json")
    assert done.status_code == 200, done.content
    assert done.json()["cover_url"].endswith(".png")
    world.messe.refresh_from_db()
    assert world.messe.cover.is_valid and world.messe.cover.file.name.startswith(f"audio-covers/{world.messe.pk}/")
    # Idempotent ; et visible dans le catalogue public.
    assert client.post(finish_url, {"file_id": data["file_id"]}, format="json").status_code == 200
    assert client_for().get(f"{API}/albums/{world.messe.pk}/").json()["album"]["cover_url"].endswith(".png")


def test_cover_rejects_wrong_type_size_content_and_foreign_files(world, media_root):
    client = client_for(world.secretaire)
    for name, kind in (("messe.gif", "image/gif"), ("messe.png", "image/jpeg"), ("messe.svg", "image/svg+xml")):
        response = _cover_start(client, world.messe, file_name=name, file_type=kind)
        assert response.status_code == 400 and response.json()["error"]["code"] == "format_image"
    big = _cover_start(client, world.messe, file_size=5 * 1024 * 1024 + 1)
    assert big.status_code == 400 and big.json()["error"]["code"] == "image_trop_grosse"
    assert _cover_start(client_for(world.fidele), world.messe).status_code == 403
    assert _cover_start(client_for(world.cure_st), world.messe).status_code == 403

    data = _cover_start(client, world.messe).json()
    fake = SimpleUploadedFile("messe.png", b"<html>pas une image</html>", content_type="image/png")
    client.post(f"{API}/staff/albums/{world.messe.pk}/pochette/{data['file_id']}/local/", {"file": fake}, format="multipart")
    bad = client.post(f"{API}/staff/albums/{world.messe.pk}/pochette/terminer/", {"file_id": data["file_id"]}, format="json")
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "format_image"

    # Le fichier d'un album ne peut pas devenir la pochette d'un autre.
    other = client.post(f"{API}/staff/albums/{world.homelies.pk}/pochette/terminer/", {"file_id": data["file_id"]}, format="json")
    assert other.status_code == 404


def test_cover_start_s3_returns_a_presigned_post_limited_to_5_mo(world, monkeypatch):
    calls = {}

    def fake_post(**kwargs):
        calls.update(kwargs)
        return {"url": "https://minio.local/jangubi", "fields": {"key": kwargs["key"]}}

    monkeypatch.setattr(storage, "is_s3", lambda: True)
    monkeypatch.setattr(storage, "presigned_post", fake_post)
    response = _cover_start(client_for(world.cure), world.messe, file_name="messe.webp", file_type="image/webp")
    assert response.status_code == 201
    assert calls["key"].startswith(f"audio-covers/{world.messe.pk}/") and calls["key"].endswith(".webp")
    assert calls["max_size"] == 5 * 1024 * 1024 and calls["content_type"] == "image/webp"


# --- 4. Accueil ----------------------------------------------------------------------------------


def test_home_sections_in_one_call(world, monkeypatch):
    monkeypatch.setattr(selectors, "current_season", lambda day=None: LiturgicalSeason.ORDINAIRE)
    kyrie = ready_track(world.chorale, "Kyrie", album=world.messe, liturgical_season=LiturgicalSeason.ORDINAIRE)
    homelie = ready_track(world.paroisse, "Homélie du 27 septembre", album=world.homelies)
    ready_track(world.chorale, "Brouillon", published=False)
    ready_track(world.source_st, "Chant de Sainte-Thérèse")
    ready_track(world.source_st, "Venez, divin Messie", liturgical_season=LiturgicalSeason.AVENT)
    playlist = services.playlist_create(
        actor=world.cure, source=world.chorale, title="Chants de la Toussaint", visibility=Visibility.PUBLIC
    )
    services.playlist_add_track(actor=world.cure, playlist=playlist, track=kyrie)
    services.playlist_update(actor=world.cure, playlist=playlist, data={"published": True})
    now = timezone.now()
    PlaybackPosition.objects.create(user=world.fidele, track=homelie, position_seconds=73.5, client_updated_at=now)
    PlaybackPosition.objects.create(user=world.fidele, track=kyrie, position_seconds=239.0, client_updated_at=now)

    data = client_for(world.fidele).get(f"{API}/accueil/").json()
    assert data["paroisse"] == {"id": str(world.sd.pk), "name": world.sd.name}
    assert [(r["track"]["title"], r["position_seconds"]) for r in data["reprendre"]] == [
        ("Homélie du 27 septembre", 73.5)
    ]  # Kyrie est fini
    assert {t["title"] for t in data["nouveautes_ma_paroisse"]} == {"Kyrie", "Homélie du 27 septembre"}
    assert [p["title"] for p in data["playlists_paroisse"]] == ["Chants de la Toussaint"]
    assert data["temps_liturgique"]["code"] == "ordinaire"
    assert data["temps_liturgique"]["label"] == "Temps ordinaire"
    assert [t["title"] for t in data["temps_liturgique"]["tracks"]] == ["Kyrie"]
    assert all("reason" in r for r in data["pour_vous"])

    # Une autre paroisse ne voit ni les nouveautés ni les contenus réservés de Saint-Dominique.
    other = client_for(world.autre).get(f"{API}/accueil/").json()
    assert {t["title"] for t in other["nouveautes_ma_paroisse"]} == {"Chant de Sainte-Thérèse", "Venez, divin Messie"}
    assert other["playlists_paroisse"] == [] and other["reprendre"] == []

    anonymous = client_for().get(f"{API}/accueil/").json()
    assert anonymous["paroisse"] is None and anonymous["reprendre"] == []
    assert anonymous["nouveautes_ma_paroisse"] == [] and anonymous["playlists_paroisse"] == []
    assert [t["title"] for t in anonymous["temps_liturgique"]["tracks"]] == ["Kyrie"]


def test_home_parish_sections_are_cached_per_parish_with_follower_rights(world, monkeypatch):
    monkeypatch.setattr(selectors, "current_season", lambda day=None: LiturgicalSeason.ORDINAIRE)
    ready_track(world.chorale, "Kyrie")
    voisine = person("voisine@test.sn", paroisse_suivie=world.sd)
    assert [t["title"] for t in client_for(world.fidele).get(f"{API}/accueil/").json()["nouveautes_ma_paroisse"]] == [
        "Kyrie"
    ]
    # Publiée sans invalidation (écriture directe) : le cache de la paroisse sert encore l'ancienne liste,
    # à une autre fidèle de la même paroisse aussi.
    ready_track(world.chorale, "Gloria")
    titles = [t["title"] for t in client_for(voisine).get(f"{API}/accueil/").json()["nouveautes_ma_paroisse"]]
    assert titles == ["Kyrie"]
    services.catalog_invalidate()
    titles = [t["title"] for t in client_for(voisine).get(f"{API}/accueil/").json()["nouveautes_ma_paroisse"]]
    assert set(titles) == {"Kyrie", "Gloria"}

    # Le staff qui suit la paroisse ne met pas ses brouillons « privés » dans le cache partagé.
    world.secretaire.paroisse_suivie = world.sd
    world.secretaire.save()
    ready_track(world.chorale, "Répétition (privée)", visibility=Visibility.PRIVE)
    services.catalog_invalidate()
    client_for(world.secretaire).get(f"{API}/accueil/")
    titles = [t["title"] for t in client_for(voisine).get(f"{API}/accueil/").json()["nouveautes_ma_paroisse"]]
    assert "Répétition (privée)" not in titles


# --- 5. Signalement d'album ----------------------------------------------------------------------


def test_album_report_and_removal_hides_the_album_and_its_tracks(world):
    kyrie = ready_track(world.chorale, "Kyrie", album=world.messe)
    created = client_for(world.fidele).post(
        f"{API}/albums/{world.messe.pk}/signaler/", {"motif": "droits", "comment": "Disque du commerce"}, format="json"
    )
    assert created.status_code == 201, created.content
    report = created.json()
    assert report["cible"] == "album" and report["track"] is None and report["album"]["id"] == str(world.messe.pk)

    # Album réservé aux membres : 404 pour une autre paroisse (on ne dit pas qu'il existe).
    assert client_for(world.autre).post(
        f"{API}/albums/{world.homelies.pk}/signaler/", {"motif": "autre"}, format="json"
    ).status_code == 404
    assert client_for().post(f"{API}/albums/{world.messe.pk}/signaler/", {"motif": "autre"}, format="json").status_code in (
        401, 403,
    )  # fmt: skip

    listed = client_for(world.cure).get(f"{API}/moderation/signalements/").json()
    assert [(r["id"], r["cible"]) for r in listed] == [(report["id"], "album")]
    assert client_for(world.cure_st).get(f"{API}/moderation/signalements/").json() == []
    done = client_for(world.cure).post(
        f"{API}/moderation/signalements/{report['id']}/traiter/", {"resolution": "retire"}, format="json"
    )
    assert done.status_code == 200 and done.json()["status"] == "retire"
    world.messe.refresh_from_db()
    kyrie.refresh_from_db()
    assert world.messe.hidden_at is not None and kyrie.hidden_at is not None
    assert client_for(world.fidele).get(f"{API}/albums/{world.messe.pk}/").status_code == 404
    assert client_for(world.fidele).post(f"{API}/pistes/{kyrie.pk}/lecture/").status_code == 404
    staff = client_for(world.secretaire).get(f"{API}/staff/albums/", {"source": str(world.chorale.pk)}).json()
    assert staff[0]["hidden_at"] is not None


# --- 6. Limite de débit des événements -----------------------------------------------------------


def _batch(track):
    return {
        "events": [
            {"client_event_id": str(uuid.uuid4()), "track_id": str(track.pk), "kind": "start",
             "occurred_at": timezone.now().isoformat()}
        ]
    }  # fmt: skip


@override_settings(AUDIO_EVENTS_THROTTLE_RATE_ANON="2/min", AUDIO_EVENTS_THROTTLE_RATE_USER="3/min")
def test_events_are_rate_limited_for_anonymous_and_signed_in_listeners(world):
    kyrie = ready_track(world.chorale, "Kyrie")
    anonymous = client_for()
    assert [anonymous.post(f"{API}/evenements/", _batch(kyrie), format="json").status_code for _ in range(3)] == [
        202, 202, 429,
    ]  # fmt: skip
    throttled = anonymous.post(f"{API}/evenements/", _batch(kyrie), format="json")
    assert throttled.json()["error"]["code"] == "throttled"
    assert int(throttled["Retry-After"]) > 0

    # Compte connecté : son propre quota, par compte (pas par adresse IP).
    fidele = client_for(world.fidele)
    assert [fidele.post(f"{API}/evenements/", _batch(kyrie), format="json").status_code for _ in range(4)] == [
        202, 202, 202, 429,
    ]  # fmt: skip
    assert client_for(world.autre).post(f"{API}/evenements/", _batch(kyrie), format="json").status_code == 202
