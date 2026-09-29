"""Monde de test de la sonothèque : paroisse Saint-Dominique (Point E, doyenné Plateau-Médina),
chorale Sainte-Cécile, Père Emmanuel Tine (curé), Marie-Thérèse Diouf (fidèle de la paroisse),
dimanche 27 septembre 2026."""

import datetime
import os
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audio import services
from apps.audio.enums import AlbumKind, SourceKind, TrackStatus, Visibility, most_restrictive
from apps.audio.models import Album, AudioSource, Track
from apps.hierarchy.tests.factories import Tree, nominate, person, priest
from apps.users.models import Profile

NOW = datetime.datetime(2026, 9, 27, 10, 0, tzinfo=datetime.UTC)


def named(user: Any, first: str, last: str) -> Any:
    Profile.objects.update_or_create(user=user, defaults={"first_name": first, "last_name": last})
    user.refresh_from_db()
    return user


def client_for(user: Any = None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def sine_file(path: str, *, seconds: int = 3, fmt: str = "mp3") -> str:
    """Vrai fichier audio généré par ffmpeg (``-f lavfi -i sine``)."""
    codec = {"mp3": ["-c:a", "libmp3lame"], "wav": [], "flac": ["-c:a", "flac"]}[fmt]
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={seconds}", "-metadata", "title=Kyrie de la messe", *codec, path,
        ],
        check=True,
    )  # fmt: skip
    return path


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def tree(db) -> Tree:
    return Tree()


@pytest.fixture
def world(tree):
    w = SimpleNamespace(tree=tree)
    w.sd, w.st, w.dakar = tree.saint_dominique, tree.sainte_therese, tree.dakar
    w.cure = named(priest("pere.tine@sd.sn"), "Emmanuel", "Tine")
    w.secretaire = named(person("secretariat@sd.sn"), "Cécile", "Coly")
    w.fidele = named(person("mt.diouf@test.sn", paroisse_suivie=w.sd), "Marie-Thérèse", "Diouf")
    w.autre = named(person("awa@test.sn", paroisse_suivie=w.st), "Awa", "Ndiaye")
    w.cure_st = priest("cure@st.sn")
    nominate(w.cure, "cure", w.sd)
    nominate(w.secretaire, "secretaire_paroissial", w.sd)
    nominate(w.cure_st, "cure", w.st)
    w.chorale = AudioSource.objects.create(node=w.sd, kind=SourceKind.CHORALE, name="Chorale Sainte-Cécile")
    w.paroisse = AudioSource.objects.create(node=w.sd, kind=SourceKind.PAROISSE, name="Paroisse Saint-Dominique")
    w.source_st = AudioSource.objects.create(node=w.st, kind=SourceKind.PAROISSE, name="Paroisse Sainte-Thérèse")
    w.messe = Album.objects.create(
        source=w.chorale,
        kind=AlbumKind.MESSE,
        title="Messe du 27 septembre 2026",
        visibility=Visibility.PUBLIC,
        recorded_on=datetime.date(2026, 9, 27),
        published_at=timezone.now(),
    )
    w.homelies = Album.objects.create(
        source=w.paroisse,
        kind=AlbumKind.HOMELIES,
        title="Homélies du Père Emmanuel Tine",
        visibility=Visibility.PAROISSE,
        published_at=timezone.now(),
    )
    return w


def ready_track(
    source: AudioSource,
    title: str,
    *,
    album: Album | None = None,
    visibility: str = Visibility.PUBLIC,
    published: bool = True,
    duration: float = 240.0,
    **fields: Any,
) -> Track:
    """Piste déjà encodée (sans passer par ffmpeg) pour les tests de catalogue."""
    track = Track.objects.create(
        source=source,
        album=album,
        title=title,
        visibility=visibility,
        effective_visibility=most_restrictive(visibility, album.visibility) if album else visibility,
        status=TrackStatus.PRET,
        version=1,
        encoded_version=1,
        duration_seconds=duration,
        waveform=[0.5] * 200,
        published_at=timezone.now() - datetime.timedelta(minutes=5) if published else None,
        **fields,
    )
    services.track_search_index(track_ids=[track.pk])
    track.refresh_from_db()
    return track


@pytest.fixture
def media_root(settings, tmp_path):
    """Dossier média propre au test (FileSystemStorage relit MEDIA_ROOT au signal setting_changed)."""
    root = tmp_path / "media"
    os.makedirs(root)
    settings.MEDIA_ROOT = str(root)
    return root
