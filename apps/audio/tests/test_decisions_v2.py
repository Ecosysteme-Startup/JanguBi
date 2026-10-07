"""Décisions du 29/09/2026 appliquées à la sonothèque : album réservé verrouillé (4), téléchargement
hors ligne (5), paroisses multiples (6-8), une lecture à la fois (10)."""

import datetime
import json

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.audio import services
from apps.audio.enums import Visibility
from apps.audio.tests.conftest import client_for, ready_track
from apps.hierarchy import services_memberships

pytestmark = pytest.mark.django_db
API = "/api/v1/audio"


# --- Décision 4 : album réservé, verrouillé pour un non-membre ------------------------------------


def test_reserved_album_shows_locked_tracks_without_urls_to_non_members(world):
    ready_track(world.paroisse, "Homélie du 27 septembre", album=world.homelies, position=1, duration=812.0)
    ready_track(world.paroisse, "Homélie du 20 septembre", album=world.homelies, position=2)
    ready_track(world.paroisse, "Brouillon", album=world.homelies, visibility=Visibility.PRIVE, position=3)

    for user in (None, world.autre):
        response = client_for(user).get(f"{API}/albums/{world.homelies.pk}/")
        assert response.status_code == 200
        data = response.json()
        assert data["album"]["verrouille"] is True
        assert data["paroisse_requise"] == {"id": str(world.sd.pk), "name": "Saint-Dominique"}
        assert [(t["title"], t["position"], t["verrouille"]) for t in data["tracks"]] == [
            ("Homélie du 27 septembre", 1, True),
            ("Homélie du 20 septembre", 2, True),
        ]
        assert data["tracks"][0]["duration_seconds"] == 812.0
        assert "url" not in json.dumps(data).replace("cover_url", "")

    member = client_for(world.fidele).get(f"{API}/albums/{world.homelies.pk}/").json()
    assert member["album"]["verrouille"] is False
    assert [t["verrouille"] for t in member["tracks"]] == [False, False]


def test_reserved_album_is_listed_locked_on_the_source_page(world):
    data = client_for(world.autre).get(f"{API}/sources/{world.paroisse.pk}/").json()
    assert [(a["title"], a["verrouille"]) for a in data["albums"]] == [("Homélies du Père Emmanuel Tine", True)]
    listed = client_for().get(f"{API}/albums/", {"source": str(world.paroisse.pk)}).json()
    assert [a["verrouille"] for a in listed] == [True]


def test_playing_a_reserved_track_is_refused_with_the_parish_to_join(world):
    homelie = ready_track(world.paroisse, "Homélie", album=world.homelies)
    brouillon = ready_track(world.paroisse, "Brouillon", visibility=Visibility.PRIVE)

    refused = client_for(world.autre).post(f"{API}/pistes/{homelie.pk}/lecture/")
    assert refused.status_code == 403
    error = refused.json()["error"]
    assert error["code"] == "reserve_paroissiens"
    assert error["details"]["paroisse"] == {"id": str(world.sd.pk), "name": "Saint-Dominique"}
    assert client_for(world.autre).post(f"{API}/pistes/{brouillon.pk}/lecture/").status_code == 404
    assert client_for(world.fidele).post(f"{API}/pistes/{homelie.pk}/lecture/").status_code == 200


def test_private_album_stays_hidden(world):
    world.homelies.visibility = Visibility.PRIVE
    world.homelies.save()
    services.catalog_invalidate()
    assert client_for(world.autre).get(f"{API}/albums/{world.homelies.pk}/").status_code == 404


# --- Décisions 6-8 : une paroisse secondaire ouvre les contenus réservés ---------------------------


def test_secondary_parish_membership_opens_reserved_content_at_once(world):
    homelie = ready_track(world.paroisse, "Homélie", album=world.homelies)
    client = client_for(world.autre)
    assert client.post(f"{API}/pistes/{homelie.pk}/lecture/").status_code == 403

    added = client.post("/api/v1/me/paroisses/", {"paroisse_id": str(world.sd.pk)}, format="json")
    assert added.status_code == 201
    assert [(r["paroisse"]["code"], r["principale"]) for r in added.json()] == [("T-ST", True), ("T-SD", False)]

    assert client.post(f"{API}/pistes/{homelie.pk}/lecture/").status_code == 200
    assert client.get(f"{API}/albums/{world.homelies.pk}/").json()["album"]["verrouille"] is False

    client.delete(f"/api/v1/me/paroisses/{world.sd.pk}/")
    assert client.post(f"{API}/pistes/{homelie.pk}/lecture/").status_code == 403


# --- Décision 5 : téléchargement hors ligne ------------------------------------------------------


def test_download_returns_a_short_signed_mp3_url_and_a_30_day_license(world):
    homelie = ready_track(world.paroisse, "Homélie", album=world.homelies)
    before = timezone.now()

    response = client_for(world.fidele).post(f"{API}/pistes/{homelie.pk}/telechargement/")

    assert response.status_code == 200
    data = response.json()
    assert data["mp3_url"].endswith("/audio.mp3") and data["version"] == 1
    url_expiry = datetime.datetime.fromisoformat(data["url_expire_le"])
    assert url_expiry <= before + datetime.timedelta(minutes=16)
    licence = data["licence"]
    expiry = datetime.datetime.fromisoformat(licence["expire_le"])
    assert datetime.timedelta(days=29, hours=23) < expiry - before <= datetime.timedelta(days=30, minutes=1)
    assert licence["paroisse_requise"] == {"id": str(world.sd.pk), "name": "Saint-Dominique"}

    public = ready_track(world.chorale, "Kyrie", album=world.messe)
    assert (
        client_for(world.autre).post(f"{API}/pistes/{public.pk}/telechargement/").json()["licence"]["paroisse_requise"]
        is None
    )
    refused = client_for(world.autre).post(f"{API}/pistes/{homelie.pk}/telechargement/")
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "reserve_paroissiens"
    assert client_for().post(f"{API}/pistes/{public.pk}/telechargement/").status_code in (401, 403)


def test_verify_renews_valid_licenses_and_lists_what_to_delete(world, tree):
    from apps.hierarchy.tests.factories import nominate, priest

    homelie = ready_track(world.paroisse, "Homélie", album=world.homelies)
    kyrie = ready_track(world.chorale, "Kyrie", album=world.messe)
    gloria = ready_track(world.chorale, "Gloria", album=world.messe)
    credo = ready_track(world.chorale, "Credo", album=world.messe)
    services_memberships.membership_join(user=world.autre, node=world.sd)  # secondaire
    url = f"{API}/telechargements/verifier/"
    unknown = "00000000-0000-4000-8000-000000000000"
    ids = [str(t.pk) for t in (homelie, kyrie, gloria, credo)] + [unknown]

    first = client_for(world.autre).post(url, {"track_ids": ids}, format="json").json()
    assert [r["statut"] for r in first["results"]] == ["valide"] * 4 + ["a_supprimer"]

    # Retirée par la paroisse, piste dépubliée, piste devenue privée.
    cure = priest("cure2@sd.sn")
    nominate(cure, "cure", world.sd)
    services_memberships.membership_remove_by_parish(actor=cure, node=world.sd, user=world.autre)
    services.track_unpublish(actor=world.cure, track=gloria)
    services.track_update(actor=world.cure, track=credo, data={"visibility": Visibility.PRIVE})

    rows = client_for(world.autre).post(url, {"track_ids": ids}, format="json").json()["results"]
    assert [(r["statut"], r["motif"]) for r in rows] == [
        ("a_supprimer", "plus_membre"),
        ("valide", ""),
        ("a_supprimer", "retiree"),
        ("a_supprimer", "privee"),
        ("a_supprimer", "introuvable"),
    ]
    assert rows[1]["expire_le"] is not None and rows[0]["expire_le"] is None
    assert client_for(world.autre).post(url, {"track_ids": []}, format="json").status_code == 400


def test_download_and_verify_are_rate_limited(world):
    kyrie = ready_track(world.chorale, "Kyrie", album=world.messe)
    with override_settings(AUDIO_DOWNLOAD_THROTTLE_RATE="1/min", AUDIO_DOWNLOAD_VERIFY_THROTTLE_RATE="1/min"):
        client = client_for(world.fidele)
        assert client.post(f"{API}/pistes/{kyrie.pk}/telechargement/").status_code == 200
        assert client.post(f"{API}/pistes/{kyrie.pk}/telechargement/").status_code == 429
        body = {"track_ids": [str(kyrie.pk)]}
        assert client.post(f"{API}/telechargements/verifier/", body, format="json").status_code == 200
        assert client.post(f"{API}/telechargements/verifier/", body, format="json").status_code == 429


# --- Décision 10 : une lecture à la fois par compte ----------------------------------------------


def test_playing_on_one_device_pauses_the_others(world, settings, django_capture_on_commit_callbacks):
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    layer = get_channel_layer()
    channel = async_to_sync(layer.new_channel)()
    async_to_sync(layer.group_add)(f"user_{world.fidele.pk}", channel)
    kyrie = ready_track(world.chorale, "Kyrie")

    body = {
        "track_id": str(kyrie.pk),
        "position_seconds": 30,
        "device_id": "web-mt-diouf",
        "client_updated_at": timezone.now().isoformat(),
        "playing": True,
    }
    with django_capture_on_commit_callbacks(execute=True):
        assert client_for(world.fidele).put(f"{API}/lecture/etat/", body, format="json").status_code == 200

    pause = async_to_sync(layer.receive)(channel)
    state = async_to_sync(layer.receive)(channel)
    assert pause["event_type"] == "playback.state" and pause["action"] == "pause"
    assert pause["sauf_device_id"] == "web-mt-diouf" and pause["track_id"] == str(kyrie.pk)
    assert state["action"] == "etat" and state["playing"] is True

    # Sans « playing » (simple sauvegarde de position) : pas de pause envoyée.
    body.update(playing=False, client_updated_at=timezone.now().isoformat())
    with django_capture_on_commit_callbacks(execute=True):
        client_for(world.fidele).put(f"{API}/lecture/etat/", body, format="json")
    only = async_to_sync(layer.receive)(channel)
    assert only["action"] == "etat" and only["playing"] is False
