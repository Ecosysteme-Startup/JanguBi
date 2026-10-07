"""Musique de démonstration : sélection versionnée, pack local jamais commité."""

import subprocess

import pytest
import yaml
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audio import seed_medias
from apps.audio.management.commands.prepare_musique_demo import SELECTION
from apps.audio.seed_medias import publish_folder, restore_folder, user_album
from apps.core.management.commands.seed_realiste import Command as SeedCommand


def _tone(path, seconds=2):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=duration={seconds}",
            str(path),
        ],
        check=True,
    )


def test_the_selection_only_keeps_named_tracks_and_warns_it_is_demo_only():
    selection = yaml.safe_load(SELECTION.read_text(encoding="utf-8"))
    assert len(selection["pistes"]) == 10
    assert "ne pas diffuser" in selection["album"]["licence"]
    assert all(t["fichier"] and t["titre"] and t["source"].endswith(".wav") for t in selection["pistes"])


def test_prepare_builds_flac_files_and_credits_read_by_the_seed(tmp_path):
    selection = yaml.safe_load(SELECTION.read_text(encoding="utf-8"))
    pack = tmp_path / "pack"
    for track in selection["pistes"][:2]:
        _tone(pack / track["source"])
    out = tmp_path / "musique-demo"

    call_command("prepare_musique_demo", pack=str(pack), sortie=str(out))

    album = user_album(str(out))
    assert [t.titre for t in album] == ["Piano gospel", "Méditation au piano"]
    assert all(t.path.suffix == ".flac" for t in album)
    assert "démonstration interne" in album[0].credit


def test_prepare_refuses_a_missing_pack(tmp_path):
    with pytest.raises(CommandError):
        call_command("prepare_musique_demo", pack=str(tmp_path / "absent"), sortie=str(tmp_path / "out"))


class _MemoryStore:
    """Double du dossier « seed-assets/ » du bucket : clés → fichiers, comme MinioStore."""

    kind = "bucket de test"

    def __init__(self, root):
        self.root = root

    def put(self, name, local):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(local.read_bytes())

    def get(self, name):
        path = self.root / name
        return path if path.exists() else None

    def list(self, prefix):
        folder = self.root / prefix
        return sorted(f"{prefix}/{p.name}" for p in folder.iterdir()) if folder.is_dir() else []


def _prepared(tmp_path):
    selection = yaml.safe_load(SELECTION.read_text(encoding="utf-8"))
    pack = tmp_path / "pack"
    _tone(pack / selection["pistes"][0]["source"], seconds=1)
    out = tmp_path / "musique-demo"
    call_command("prepare_musique_demo", pack=str(pack), sortie=str(out))
    return out


def test_published_folder_is_restored_after_a_reset(tmp_path):
    out = _prepared(tmp_path)
    bucket = _MemoryStore(tmp_path / "bucket")

    assert publish_folder(bucket, out) == 2  # 1 FLAC + credits.yaml
    restored = restore_folder(bucket, tmp_path / "reprise")

    album = user_album(str(restored))
    assert [t.titre for t in album] == ["Piano gospel"]
    assert "démonstration interne" in album[0].credit


def test_restore_returns_none_when_nothing_was_published(tmp_path):
    assert restore_folder(_MemoryStore(tmp_path / "vide"), tmp_path / "reprise") is None


def test_publier_refuses_without_minio(tmp_path, settings):
    settings.AWS_S3_ACCESS_KEY_ID = ""
    selection = yaml.safe_load(SELECTION.read_text(encoding="utf-8"))
    pack = tmp_path / "pack"
    _tone(pack / selection["pistes"][0]["source"], seconds=1)
    with pytest.raises(CommandError, match="MinIO non configuré"):
        call_command("prepare_musique_demo", pack=str(pack), sortie=str(tmp_path / "out"), publier=True)


def test_seed_reads_the_demo_music_from_the_bucket(tmp_path, monkeypatch, settings):
    out = _prepared(tmp_path)
    bucket = _MemoryStore(tmp_path / "bucket")
    publish_folder(bucket, out)
    settings.BASE_DIR = tmp_path / "sans-pack"
    monkeypatch.setenv("JANGUBI_SEED_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(seed_medias, "store_for", lambda profil: bucket)

    folder = SeedCommand()._musique_demo("recette")

    assert [t.titre for t in user_album(folder)] == ["Piano gospel"]


def test_seed_explains_how_to_publish_when_the_demo_music_is_missing(tmp_path, monkeypatch, settings):
    settings.BASE_DIR = tmp_path / "sans-pack"
    monkeypatch.setenv("JANGUBI_SEED_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(seed_medias, "store_for", lambda profil: _MemoryStore(tmp_path / "vide"))

    with pytest.raises(CommandError, match="--publier"):
        SeedCommand()._musique_demo("recette")


class _FakeS3:
    """Double du client boto3 : enregistre les appels et refuse toute action de niveau bucket,
    comme la clé MinIO de la recette (elle n'ouvre que le bucket de l'application)."""

    def __init__(self):
        self.objects = {}
        self.calls = []

    def head_bucket(self, **kwargs):
        raise AssertionError("aucune action de niveau bucket : la clé de recette ne l'autorise pas")

    create_bucket = head_bucket

    def upload_file(self, filename, bucket, key):
        self.calls.append(("put", bucket, key))
        self.objects[(bucket, key)] = open(filename, "rb").read()

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise KeyError(Key)

    def download_file(self, bucket, key, filename):
        self.calls.append(("get", bucket, key))
        with open(filename, "wb") as fh:
            fh.write(self.objects[(bucket, key)])

    def get_paginator(self, _name):
        store = self

        class _Pages:
            def paginate(self, Bucket, Prefix):
                return [{"Contents": [{"Key": k} for (b, k) in store.objects if b == Bucket and k.startswith(Prefix)]}]

        return _Pages()


def test_recette_store_lives_under_seed_assets_in_the_app_bucket(tmp_path, monkeypatch, settings):
    fake = _FakeS3()
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake)
    monkeypatch.setenv("JANGUBI_SEED_CACHE", str(tmp_path / "cache"))
    settings.AWS_STORAGE_BUCKET_NAME = "jangubi-staging"
    settings.AWS_S3_ACCESS_KEY_ID = "cle-de-test"
    settings.AWS_S3_SECRET_ACCESS_KEY = "secret-de-test"
    folder = tmp_path / "musique-demo"
    folder.mkdir()
    (folder / "01-piano.flac").write_bytes(b"flac")
    (folder / "credits.yaml").write_text("album: {}\n", encoding="utf-8")

    store = seed_medias.store_for("recette")
    count = publish_folder(store, folder)

    assert count == 2
    assert {key for (_, bucket, key) in fake.calls if bucket == "jangubi-staging"} == {
        "seed-assets/musique-demo/01-piano.flac",
        "seed-assets/musique-demo/credits.yaml",
    }
    assert store.list("musique-demo") == ["musique-demo/01-piano.flac", "musique-demo/credits.yaml"]
    assert store.has("musique-demo/credits.yaml")
    assert store.get("musique-demo/01-piano.flac").read_bytes() == b"flac"
