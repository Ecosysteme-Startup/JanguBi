"""Fabrique le dossier de musique de démonstration à partir du pack décompressé (``seed_assets/musique-demo.yaml``).

    python manage.py prepare_musique_demo
    python manage.py prepare_musique_demo --pack "/chemin/The Polyphonic Elements Vol.6" --sortie /tmp/musique
    python manage.py prepare_musique_demo --publier   # recette : copie aussi sous seed-assets/ dans le bucket de l'app

Convertit les pistes retenues en FLAC et écrit ``credits.yaml`` (lu par ``seed_realiste --medias-dossier``).
Rien n'entre dans Git (``seed_assets/`` est ignoré). ``--publier`` copie le dossier dans le bucket MinIO
``seed-assets/musique-demo/`` du bucket MinIO de l'app, en recette : ``seed_realiste --musique-demo`` l'y reprend après un
reset, sans le pack. Jamais en production (licence du pack : démonstration interne).
"""

from __future__ import annotations

import pathlib
import subprocess
from typing import Any

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.audio.seed_medias import LocalStore, publish_folder, store_for

ROOT = pathlib.Path(settings.BASE_DIR) / "seed_assets"
SELECTION = ROOT / "musique-demo.yaml"


class Command(BaseCommand):
    help = "Prépare seed_assets/musique-demo/ (FLAC + credits.yaml) depuis le pack de samples décompressé."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--pack", default=None, help="Dossier du pack décompressé (défaut : seed_assets/<pack>).")
        parser.add_argument("--sortie", default=str(ROOT / "musique-demo"), help="Dossier produit.")
        parser.add_argument("--publier", action="store_true",
                            help="Copie aussi le dossier sous seed-assets/ dans le bucket MinIO de l'app (recette).")  # fmt: skip

    def handle(self, *args: Any, pack: str | None, sortie: str, publier: bool = False, **options: Any) -> None:
        selection = yaml.safe_load(SELECTION.read_text(encoding="utf-8"))
        source = pathlib.Path(pack).expanduser() if pack else ROOT / selection["pack"]
        if not source.is_dir():
            raise CommandError(f"Pack introuvable : {source}. Décompressez l'archive dans seed_assets/ ou passez --pack.")
        out = pathlib.Path(sortie).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        credits: dict[str, Any] = {"album": selection["album"], "pistes": {}}
        missing = []
        for track in selection["pistes"]:
            src = source / track["source"]
            if not src.exists():
                missing.append(track["source"])
                continue
            name = f"{track['fichier']}.flac"
            subprocess.run(
                [settings.AUDIO_FFMPEG_BIN, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                 "-i", str(src), "-c:a", "flac", str(out / name)],
                check=True, timeout=600,
            )  # fmt: skip
            stem = pathlib.Path(track["source"]).stem
            credits["pistes"][name] = {
                "titre": track["titre"],
                "attribution": f"{selection['album']['artiste']} · « {stem} » · démonstration interne",
            }
            self.stdout.write(f"  {name} ← {track['source']}")
        (out / "credits.yaml").write_text(yaml.safe_dump(credits, allow_unicode=True, sort_keys=False), encoding="utf-8")
        for name in missing:
            self.stdout.write(self.style.WARNING(f"  absente du pack : {name}"))
        done = len(credits["pistes"])
        self.stdout.write(self.style.SUCCESS(f"{done} piste(s) prête(s) dans {out}."))
        if not done:
            raise CommandError("Aucune piste préparée.")
        if publier:
            store = store_for("recette")
            if isinstance(store, LocalStore):
                raise CommandError("--publier : MinIO non configuré (AWS_S3_ACCESS_KEY_ID absent).")
            count = publish_folder(store, out)
            self.stdout.write(self.style.SUCCESS(f"{count} fichier(s) copiés dans {store.kind}, dossier musique-demo/."))
