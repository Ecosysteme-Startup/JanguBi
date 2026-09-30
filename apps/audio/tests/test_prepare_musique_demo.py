"""Musique de démonstration : sélection versionnée, pack local jamais commité."""

import subprocess

import pytest
import yaml
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audio.management.commands.prepare_musique_demo import SELECTION
from apps.audio.seed_medias import user_album


def _tone(path, seconds=2):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"sine=duration={seconds}", str(path)],
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
