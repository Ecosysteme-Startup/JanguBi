"""Catalogue (cache 10 min invalidé à la publication), recherche, bibliothèque et playlists."""

import pytest

from apps.audio import services
from apps.audio.enums import LiturgicalSeason, Visibility
from apps.audio.models import Playlist
from apps.audio.tests.conftest import client_for, ready_track

pytestmark = pytest.mark.django_db

API = "/api/v1/audio"


# --- Catalogue -------------------------------------------------------------------------------


def test_sources_are_listed_alphabetically_without_counts(world):
    data = client_for().get(f"{API}/sources/").json()
    assert [s["name"] for s in data] == [
        "Chorale Sainte-Cécile",
        "Paroisse Saint-Dominique",
        "Paroisse Sainte-Thérèse",
    ]
    assert all("play_count" not in s for s in data)


def test_most_played_only_inside_a_source(world):
    ready_track(world.chorale, "Kyrie", play_count=12)
    ready_track(world.chorale, "Gloria", play_count=40)
    ready_track(world.source_st, "Magnificat", play_count=999)  # autre paroisse : jamais comparée
    data = client_for().get(f"{API}/sources/{world.chorale.pk}/").json()
    assert [t["title"] for t in data["most_played"]] == ["Gloria", "Kyrie"]
    assert all("play_count" not in t for t in data["most_played"])


def test_source_page_is_cached_and_invalidated_on_publication(world, django_assert_max_num_queries):
    client = client_for()
    url = f"{API}/sources/{world.chorale.pk}/"
    ready_track(world.chorale, "Kyrie")
    assert [t["title"] for t in client.get(url).json()["recent"]] == ["Kyrie"]
    with django_assert_max_num_queries(3):  # la source seulement : le reste vient du cache
        client.get(url)

    sanctus = ready_track(world.chorale, "Sanctus", published=False)
    assert [t["title"] for t in client.get(url).json()["recent"]] == ["Kyrie"]  # pas encore publié
    services.track_publish(actor=world.cure, track=sanctus)
    services.catalog_invalidate()  # on_commit ne s'exécute pas dans un test transactionnel
    assert {t["title"] for t in client.get(url).json()["recent"]} == {"Kyrie", "Sanctus"}


def test_publication_invalidates_the_catalog_on_commit(world, django_capture_on_commit_callbacks):
    before = services.catalog_version()
    track = ready_track(world.chorale, "Kyrie", published=False)
    with django_capture_on_commit_callbacks(execute=True):
        services.track_publish(actor=world.cure, track=track)
    assert services.catalog_version() == before + 1


def test_cache_is_split_by_access_level(world):
    ready_track(world.paroisse, "Homélie du 27 septembre", album=world.homelies)
    url = f"{API}/sources/{world.paroisse.pk}/"
    assert client_for().get(url).json()["recent"] == []  # anonyme d'abord (mis en cache)
    assert [t["title"] for t in client_for(world.fidele).get(url).json()["recent"]] == ["Homélie du 27 septembre"]
    assert client_for(world.autre).get(url).json()["recent"] == []


def test_album_page_lists_tracks_in_order_and_hides_private_albums(world):
    ready_track(world.chorale, "Gloria", album=world.messe, position=2)
    ready_track(world.chorale, "Kyrie", album=world.messe, position=1)
    data = client_for().get(f"{API}/albums/{world.messe.pk}/").json()
    assert data["album"]["title"] == "Messe du 27 septembre 2026"
    assert [t["title"] for t in data["tracks"]] == ["Kyrie", "Gloria"]
    # Album réservé (décision 4) : visible verrouillé pour un non-membre ; un brouillon reste 404.
    locked = client_for().get(f"{API}/albums/{world.homelies.pk}/")
    assert locked.status_code == 200 and locked.json()["album"]["verrouille"] is True
    assert client_for(world.fidele).get(f"{API}/albums/{world.homelies.pk}/").json()["album"]["verrouille"] is False
    world.homelies.published_at = None
    world.homelies.save()
    services.catalog_invalidate()
    assert client_for().get(f"{API}/albums/{world.homelies.pk}/").status_code == 404


def test_staff_creates_album_publishes_and_edits_track(world):
    client = client_for(world.cure)
    album = client.post(
        f"{API}/albums/",
        {"source_id": str(world.paroisse.pk), "kind": "retraite", "title": "Retraite de Carême 2026",
         "visibility": "public", "liturgical_season": "careme"},
        format="json",
    ).json()  # fmt: skip
    assert album["visibility"] == "public" and album["published_at"] is None
    track = ready_track(world.paroisse, "Premier enseignement", published=False)
    patch = client.patch(
        f"{API}/pistes/{track.pk}/",
        {"album_id": album["id"], "performers": ["Père Emmanuel Tine"], "language": "fr", "tags": ["retraite"]},
        format="json",
    )
    assert patch.status_code == 200, patch.content
    assert patch.json()["album"]["id"] == album["id"]
    assert client.post(f"{API}/albums/{album['id']}/publier/").status_code == 200
    track.refresh_from_db()
    assert track.published_at is not None
    assert client_for(world.fidele).patch(f"{API}/pistes/{track.pk}/", {"title": "x"}, format="json").status_code == 403


# --- Recherche -------------------------------------------------------------------------------


def test_search_is_accent_insensitive_and_weighted(world):
    careme = ready_track(
        world.paroisse, "Homélie du premier dimanche de Carême", liturgical_season=LiturgicalSeason.CAREME
    )
    ready_track(world.chorale, "Kyrie", description="Messe chantée pendant le carême")
    data = client_for().get(f"{API}/recherche/", {"q": "careme"}).json()
    titles = [t["title"] for t in data["results"]]
    assert titles[0] == careme.title  # le titre (A) passe avant la description (C)
    assert "Kyrie" in titles


def test_search_tolerates_typos_on_titles(world):
    ready_track(world.chorale, "Sanctus de la messe de Keur Moussa")
    data = client_for().get(f"{API}/recherche/", {"q": "Sanctsu de la mese"}).json()
    assert [t["title"] for t in data["results"]] == ["Sanctus de la messe de Keur Moussa"]


def test_search_finds_source_and_album_names(world):
    ready_track(world.chorale, "Kyrie", album=world.messe)
    assert client_for().get(f"{API}/recherche/", {"q": "Sainte-Cécile"}).json()["results"][0]["title"] == "Kyrie"


def test_search_filters_by_visibility_first(world):
    ready_track(world.paroisse, "Homélie sur la miséricorde", album=world.homelies)
    assert client_for().get(f"{API}/recherche/", {"q": "miséricorde"}).json()["results"] == []
    assert len(client_for(world.fidele).get(f"{API}/recherche/", {"q": "misericorde"}).json()["results"]) == 1


def test_search_cursor_pagination_orders_by_relevance_then_popularity(world):
    for i, plays in enumerate([5, 50, 20, 1, 30]):
        ready_track(world.chorale, f"Alléluia {i}", play_count=plays)
    client = client_for()
    first = client.get(f"{API}/recherche/", {"q": "alleluia", "limit": 2}).json()
    assert [t["title"] for t in first["results"]] == ["Alléluia 1", "Alléluia 4"]
    second = client.get(f"{API}/recherche/", {"q": "alleluia", "limit": 2, "cursor": first["next_cursor"]}).json()
    assert [t["title"] for t in second["results"]] == ["Alléluia 2", "Alléluia 0"]
    third = client.get(f"{API}/recherche/", {"q": "alleluia", "limit": 2, "cursor": second["next_cursor"]}).json()
    assert [t["title"] for t in third["results"]] == ["Alléluia 3"] and third["next_cursor"] is None
    bad = client.get(f"{API}/recherche/", {"q": "alleluia", "cursor": "%%%"})
    assert bad.status_code == 400


# --- Likes, playlists, bibliothèque ----------------------------------------------------------


def test_likes_playlists_and_library(world):
    kyrie = ready_track(world.chorale, "Kyrie", album=world.messe)
    gloria = ready_track(world.chorale, "Gloria", album=world.messe)
    homelie = ready_track(world.paroisse, "Homélie", album=world.homelies)
    client = client_for(world.fidele)

    assert client.put(f"{API}/pistes/{kyrie.pk}/like/").json() == {"liked": True}
    assert client.put(f"{API}/pistes/{kyrie.pk}/like/").json() == {"liked": True}  # idempotent
    kyrie.refresh_from_db()
    assert kyrie.like_count == 1

    playlist = client.post(f"{API}/playlists/", {"title": "Pour le dimanche"}, format="json").json()
    assert playlist["visibility"] == "prive" and playlist["is_editorial"] is False
    for track in (kyrie, gloria, homelie):
        assert (
            client.post(
                f"{API}/playlists/{playlist['id']}/pistes/", {"track_id": str(track.pk)}, format="json"
            ).status_code
            == 201
        )
    order = client.put(
        f"{API}/playlists/{playlist['id']}/ordre/",
        {"track_ids": [str(homelie.pk), str(kyrie.pk), str(gloria.pk)]},
        format="json",
    ).json()
    assert [t["title"] for t in order["tracks"]] == ["Homélie", "Kyrie", "Gloria"]
    assert (
        client.put(
            f"{API}/playlists/{playlist['id']}/ordre/", {"track_ids": [str(kyrie.pk)]}, format="json"
        ).status_code
        == 400
    )
    assert client.delete(f"{API}/playlists/{playlist['id']}/pistes/{gloria.pk}/").status_code == 204

    # Playlist privée : invisible des autres ; une piste « paroisse » y reste filtrée par droits.
    assert client_for(world.autre).get(f"{API}/playlists/{playlist['id']}/").status_code == 404
    client.patch(f"{API}/playlists/{playlist['id']}/", {"visibility": "public"}, format="json")
    shared = client_for(world.autre).get(f"{API}/playlists/{playlist['id']}/").json()
    assert [t["title"] for t in shared["tracks"]] == ["Kyrie"]
    assert (
        client_for(world.autre).patch(f"{API}/playlists/{playlist['id']}/", {"title": "x"}, format="json").status_code
        == 404
    )

    services.playback_state_update(
        user=world.fidele, track=gloria, position_seconds=30, device_id="web", client_updated_at=world.messe.created_at
    )
    library = client.get(f"{API}/bibliotheque/").json()
    assert [t["title"] for t in library["likes"]] == ["Kyrie"]
    assert [p["title"] for p in library["playlists"]] == ["Pour le dimanche"]
    assert library["recent"][0]["track"]["title"] == "Gloria" and library["recent"][0]["position_seconds"] == 30

    assert client.delete(f"{API}/pistes/{kyrie.pk}/like/").json() == {"liked": False}
    assert client.delete(f"{API}/playlists/{playlist['id']}/").status_code == 204


def test_editorial_playlist_of_a_source(world):
    kyrie = ready_track(world.chorale, "Kyrie")
    client = client_for(world.cure)
    playlist = client.post(
        f"{API}/playlists/",
        {"title": "Chants de la Toussaint", "source_id": str(world.chorale.pk), "visibility": "public"},
        format="json",
    ).json()
    assert playlist["is_editorial"] is True
    client.post(f"{API}/playlists/{playlist['id']}/pistes/", {"track_id": str(kyrie.pk)}, format="json")
    assert client_for().get(f"{API}/playlists/{playlist['id']}/").status_code == 404  # pas encore publiée
    client.patch(f"{API}/playlists/{playlist['id']}/", {"published": True}, format="json")
    assert [t["title"] for t in client_for().get(f"{API}/playlists/{playlist['id']}/").json()["tracks"]] == ["Kyrie"]
    services.catalog_invalidate()
    page = client_for().get(f"{API}/sources/{world.chorale.pk}/").json()
    assert [p["title"] for p in page["playlists"]] == ["Chants de la Toussaint"]
    assert (
        client_for(world.fidele)
        .post(f"{API}/playlists/", {"title": "x", "source_id": str(world.chorale.pk)}, format="json")
        .status_code
        == 403
    )
    assert Playlist.objects.filter(source=world.chorale).count() == 1


def test_personal_playlist_cannot_be_parish_only(world):
    response = client_for(world.fidele).post(
        f"{API}/playlists/", {"title": "x", "visibility": Visibility.PAROISSE}, format="json"
    )
    assert response.status_code == 400


# --- Modération ------------------------------------------------------------------------------


def test_report_and_moderation(world):
    kyrie = ready_track(world.chorale, "Kyrie")
    report = (
        client_for(world.fidele)
        .post(
            f"{API}/pistes/{kyrie.pk}/signaler/",
            {"motif": "droits", "comment": "Enregistrement d'un disque"},
            format="json",
        )
        .json()
    )
    assert report["status"] == "ouvert"
    assert client_for(world.secretaire).get(f"{API}/moderation/signalements/").json() == []  # pas audio.moderer
    listed = client_for(world.cure).get(f"{API}/moderation/signalements/").json()
    assert [r["id"] for r in listed] == [report["id"]]
    assert (
        client_for(world.cure_st)
        .post(f"{API}/moderation/signalements/{report['id']}/traiter/", {"resolution": "retire"}, format="json")
        .status_code
        == 403
    )
    done = client_for(world.cure).post(
        f"{API}/moderation/signalements/{report['id']}/traiter/", {"resolution": "retire"}, format="json"
    )
    assert done.json()["status"] == "retire"
    kyrie.refresh_from_db()
    assert kyrie.hidden_at is not None
    assert client_for(world.fidele).post(f"{API}/pistes/{kyrie.pk}/lecture/").status_code == 404


def test_staff_views(world):
    ready_track(world.chorale, "Kyrie", published=False)
    sources = client_for(world.secretaire).get(f"{API}/staff/sources/").json()
    assert {s["name"] for s in sources} == {"Chorale Sainte-Cécile", "Paroisse Saint-Dominique"}
    tracks = client_for(world.secretaire).get(f"{API}/staff/pistes/", {"source": str(world.chorale.pk)}).json()
    assert tracks[0]["status"] == "pret" and tracks[0]["published_at"] is None
    assert client_for(world.fidele).get(f"{API}/staff/pistes/", {"source": str(world.chorale.pk)}).status_code == 403
