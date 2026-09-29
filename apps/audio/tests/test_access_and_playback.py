"""Lecture : identité, autorisation (visibilité, appartenance), URL signée, reprise, synchro."""

import datetime
import time
from urllib.parse import parse_qs, urlparse

import pytest
from django.utils import timezone

from apps.audio import access, services, signing
from apps.audio.enums import TrackStatus, Visibility
from apps.audio.models import PlaybackPosition, Track
from apps.audio.tests.conftest import client_for, ready_track

pytestmark = pytest.mark.django_db


def _play(user, track):
    return client_for(user).post(f"/api/v1/audio/pistes/{track.pk}/lecture/")


# --- Visibilité -------------------------------------------------------------------------------


def test_visibility_matrix(world):
    kyrie = ready_track(world.chorale, "Kyrie", album=world.messe)  # public
    homelie = ready_track(world.paroisse, "Homélie du 27 septembre", album=world.homelies)  # album « paroisse »
    brouillon = ready_track(world.chorale, "Gloria (répétition)", visibility=Visibility.PRIVE)

    expected = {
        None: {kyrie},
        world.fidele: {kyrie, homelie},  # paroisse suivie : Saint-Dominique
        world.autre: {kyrie},  # fidèle de Sainte-Thérèse
        world.cure: {kyrie, homelie, brouillon},  # audio.publier sur Saint-Dominique
        world.cure_st: {kyrie},
    }
    for user, tracks in expected.items():
        m = access.membership(user)
        assert set(access.listenable_tracks(m)) == tracks, user
        for track in (kyrie, homelie, brouillon):
            assert (_play(user, track).status_code == 200) is (track in tracks), (user, track.title)


def test_album_visibility_restricts_its_tracks(world):
    track = ready_track(world.paroisse, "Homélie", album=world.homelies, visibility=Visibility.PUBLIC)
    assert track.effective_visibility == Visibility.PAROISSE
    services.album_update(actor=world.cure, album=world.homelies, data={"visibility": Visibility.PUBLIC})
    track.refresh_from_db()
    assert track.effective_visibility == Visibility.PUBLIC
    assert _play(None, track).status_code == 200


def test_staff_of_the_diocese_above_is_a_member(world, tree):
    from apps.hierarchy.tests.factories import nominate, person

    chancelier = person("chancelier@dakar.sn")
    nominate(chancelier, "chancelier", tree.dakar)
    homelie = ready_track(world.paroisse, "Homélie", album=world.homelies)
    assert _play(chancelier, homelie).status_code == 200


def test_unpublished_hidden_or_not_ready_tracks_are_not_playable(world):
    draft = ready_track(world.chorale, "Sanctus", published=False)
    hidden = ready_track(world.chorale, "Agnus Dei", hidden_at=timezone.now())
    assert _play(world.fidele, draft).status_code == 404
    assert _play(world.fidele, hidden).status_code == 404
    assert _play(world.cure, draft).status_code == 200  # le staff pré-écoute
    encoding = ready_track(world.chorale, "Credo")
    Track.objects.filter(pk=encoding.pk).update(status=TrackStatus.ENCODAGE, encoded_version=None)
    response = _play(world.cure, encoding)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "piste_pas_prete"


def test_authorization_decision_is_cached_but_follows_unpublication(world, django_assert_max_num_queries):
    track = ready_track(world.chorale, "Kyrie")
    assert access.can_play(world.fidele, track)
    with django_assert_max_num_queries(0):
        assert access.can_play(world.fidele, track)  # cache 5 min
    services.track_unpublish(actor=world.cure, track=track)
    track.refresh_from_db()
    assert not access.can_play(world.fidele, track)  # la clé inclut updated_at


# --- Réponse de lecture -----------------------------------------------------------------------


def test_playback_returns_url_resume_waveform_and_metadata(world):
    track = ready_track(world.chorale, "Kyrie", album=world.messe, performers=["Chorale Sainte-Cécile"])
    PlaybackPosition.objects.create(
        user=world.fidele, track=track, position_seconds=73.5, device_id="iphone-mt", client_updated_at=timezone.now()
    )
    data = _play(world.fidele, track).json()
    assert data["track"]["title"] == "Kyrie"
    assert data["track"]["album"]["title"] == "Messe du 27 septembre 2026"
    assert data["track"]["source"]["name"] == "Chorale Sainte-Cécile"
    assert data["stream"]["master_url"].endswith(f"/media/audio-hls/{track.pk}/1/master.m3u8")
    assert data["stream"]["mp3_url"].endswith(f"/audio-hls/{track.pk}/1/audio.mp3")
    assert data["resume"] == {"position_seconds": 73.5, "device_id": "iphone-mt", "updated_at": data["resume"]["updated_at"]}
    assert len(data["waveform"]) == 200
    assert _play(None, track).json()["resume"] is None  # anonyme : pas de reprise


def test_finished_track_restarts_from_the_beginning(world):
    track = ready_track(world.chorale, "Kyrie", duration=240)
    PlaybackPosition.objects.create(
        user=world.fidele, track=track, position_seconds=238, device_id="web", client_updated_at=timezone.now()
    )
    assert _play(world.fidele, track).json()["resume"] is None


def test_cdn_url_is_signed_on_the_versioned_prefix(world, settings):
    settings.AUDIO_CDN_BASE_URL = "https://audio.jangubi.sn"
    settings.AUDIO_CDN_SIGNING_SECRET = "secret-de-test"
    track = ready_track(world.chorale, "Kyrie")
    data = _play(world.fidele, track).json()
    url = urlparse(data["stream"]["master_url"])
    assert url.netloc == "audio.jangubi.sn"
    assert url.path == f"/audio-hls/{track.pk}/1/master.m3u8"
    token = parse_qs(url.query)["verify"][0]
    expires = int(token.split("-", 1)[0])
    assert 6 * 3600 - 60 <= expires - time.time() <= 6 * 3600 + 60

    # Le même jeton ouvre les segments de la même version (signature du préfixe)…
    assert signing.verify_path(f"/audio-hls/{track.pk}/1/bas/seg_00003.ts", token)
    assert signing.verify_path(url.path, token)
    # … mais ni une autre version, ni une autre piste, ni un jeton altéré ou expiré.
    assert not signing.verify_path(f"/audio-hls/{track.pk}/2/master.m3u8", token)
    assert not signing.verify_path("/audio-hls/00000000-0000-0000-0000-000000000000/1/master.m3u8", token)
    assert not signing.verify_path(url.path, token[:-2] + "xx")
    assert not signing.verify_path(url.path, token, now=expires + 1)
    assert not signing.verify_path(url.path, "n'importe-quoi")


def test_signature_matches_the_documented_algorithm(settings):
    import base64
    import hashlib
    import hmac

    settings.AUDIO_CDN_SIGNING_SECRET = "s3cr3t"
    prefix = "/audio-hls/abc/3/"
    mac = hmac.new(b"s3cr3t", f"{prefix}1790000000".encode(), hashlib.sha256).digest()
    expected = base64.urlsafe_b64encode(mac).decode().rstrip("=")
    assert signing.sign_prefix(prefix, 1790000000) == f"1790000000-{expected}"


# --- Reprise et synchronisation multi-appareils -----------------------------------------------

STATE = "/api/v1/audio/lecture/etat/"


def _put(user, track, position, device, at):
    return client_for(user).put(
        STATE,
        {"track_id": str(track.pk), "position_seconds": position, "device_id": device, "client_updated_at": at.isoformat()},
        format="json",
    )


def test_playback_state_last_write_wins_with_bounded_client_clock(world):
    kyrie = ready_track(world.chorale, "Kyrie", duration=300)
    gloria = ready_track(world.chorale, "Gloria", duration=300)
    now = timezone.now()

    assert client_for(world.fidele).get(STATE).status_code == 204
    assert _put(world.fidele, kyrie, 42, "android-mt", now - datetime.timedelta(seconds=30)).json()["applied"]
    # Un appareil en retard (horodatage plus ancien) ne remplace pas l'état…
    late = _put(world.fidele, gloria, 10, "web-mt", now - datetime.timedelta(seconds=60)).json()
    assert late["applied"] is False
    assert late["state"]["track"]["title"] == "Kyrie"
    # … mais sa position dans Gloria est gardée pour la reprise de Gloria.
    assert PlaybackPosition.objects.get(user=world.fidele, track=gloria).position_seconds == 10

    # Une horloge d'appareil dans le futur est ramenée à l'heure serveur.
    future = _put(world.fidele, kyrie, 55, "android-mt", now + datetime.timedelta(days=2)).json()
    assert future["applied"]
    stamp = datetime.datetime.fromisoformat(future["state"]["updated_at"])
    assert stamp <= timezone.now()
    # Position bornée à la durée de la piste.
    assert _put(world.fidele, kyrie, 9999, "web-mt", timezone.now()).json()["state"]["position_seconds"] == 300

    state = client_for(world.fidele).get(STATE).json()
    assert state["track"]["title"] == "Kyrie" and state["device_id"] == "web-mt"


def test_playback_state_is_pushed_to_the_user_group(world, settings, django_capture_on_commit_callbacks):
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    layer = get_channel_layer()
    channel = async_to_sync(layer.new_channel)()
    async_to_sync(layer.group_add)(f"user_{world.fidele.pk}", channel)

    track = ready_track(world.chorale, "Kyrie")
    with django_capture_on_commit_callbacks(execute=True):
        _put(world.fidele, track, 12.5, "iphone-mt", timezone.now())
    message = async_to_sync(layer.receive)(channel)
    assert message["type"] == "notification.push"
    assert message["event_type"] == "playback.state"
    assert message["track_id"] == str(track.pk) and message["position_seconds"] == 12.5
    assert message["device_id"] == "iphone-mt"


def test_playback_state_requires_the_right_to_listen(world):
    homelie = ready_track(world.paroisse, "Homélie", album=world.homelies)
    assert _put(world.autre, homelie, 5, "web", timezone.now()).status_code == 404
