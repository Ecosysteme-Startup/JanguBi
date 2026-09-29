"""Télécharge une fois les médias du manifeste ``seed_assets/manifest.yaml`` (domaine public, CC0, CC BY),
vérifie leur sha256 et les range dans le cache local ou le bucket MinIO ``seed-assets`` (recette).

    python manage.py fetch_seed_assets                    # cache local (~/.cache/jangubi-seed/)
    python manage.py fetch_seed_assets --profil recette   # bucket MinIO « seed-assets »
    python manage.py fetch_seed_assets --epingler         # écrit dans le manifeste les sha256 manquants

Un fichier injoignable ou dont l'empreinte diffère est signalé et ignoré : le semis se replie sur
les médias générés (ffmpeg, Piper). Jamais d'échec bloquant.
"""

from __future__ import annotations

import re
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.audio import seed_medias


class Command(BaseCommand):
    help = "Télécharge les médias libres des données de test (manifeste versionné, sha256 vérifiés)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--profil", choices=["local", "recette"], default="local")
        parser.add_argument("--epingler", action="store_true", help="Écrit dans le manifeste les sha256 manquants.")
        parser.add_argument("--timeout", type=int, default=60)

    def handle(self, *args: Any, profil: str, epingler: bool, timeout: int, **options: Any) -> None:
        assets = seed_medias.load_manifest()
        store = seed_medias.store_for(profil)
        self.stdout.write(f"{len(assets)} fichier(s) au manifeste, rangement : {store.kind}")
        pins: dict[str, str] = {}
        ok = 0
        for asset in assets:
            try:
                state, digest = seed_medias.fetch(asset, store, timeout=timeout)
            except Exception as exc:  # noqa: BLE001 - réseau, 404 : on signale et on continue
                self.stdout.write(self.style.WARNING(f"  {asset.id} : injoignable ({exc.__class__.__name__})"))
                continue
            ok += state in ("téléchargé", "déjà présent")
            if not asset.sha256 and digest:
                pins[asset.id] = digest
            self.stdout.write(f"  {asset.id} : {state} ({digest[:12]}…)")
        if epingler and pins:
            path = seed_medias.manifest_path()
            text = path.read_text(encoding="utf-8")
            for asset_id, digest in pins.items():
                text = re.sub(
                    rf"(- id: {re.escape(asset_id)}\n(?:    .*\n)*?    sha256:)[ \t]*\n", rf"\1 {digest}\n", text, count=1
                )
            path.write_text(text, encoding="utf-8")
            self.stdout.write(f"{len(pins)} empreinte(s) épinglée(s) dans {path}.")
        self.stdout.write(self.style.SUCCESS(f"{ok}/{len(assets)} fichier(s) disponible(s)."))
