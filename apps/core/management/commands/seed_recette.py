"""Recette complète en une commande : données réelles (``seed_prod``), personnes de démonstration
(``seed_demo``), monde de test réaliste (``seed_realiste``) et musique de démo. Jamais en production.

    SEED_ALLOWED=true python manage.py seed_recette                    # échelle moyenne, musique de démo
    SEED_ALLOWED=true python manage.py seed_recette --echelle petite   # plus rapide (local)
    SEED_ALLOWED=true python manage.py seed_recette --reset            # retire les données de test (MANUEL)

La musique de démo vient de ``seed_assets/musique-demo/`` ou de ``seed-assets/`` dans le bucket de l'app (publiée une fois par
``prepare_musique_demo --publier``) ; absente, le seed continue avec les médias légers du manifeste.
"""

from __future__ import annotations

from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.core.seeding.context import SCALES
from apps.core.seeding.guards import SeedRefused, check_allowed


class Command(BaseCommand):
    help = "Recette complète : seed_prod + démonstration + données de test + musique de démo. Jamais en production."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--echelle", choices=list(SCALES), default="moyenne")
        parser.add_argument("--graine", type=int, default=2026)
        parser.add_argument("--sans-musique", dest="sans_musique", action="store_true")
        parser.add_argument("--hors-ligne", dest="hors_ligne", action="store_true", help="Sans AELF ni téléchargement.")
        parser.add_argument("--reset", action="store_true", help="Retire les données de test et de démonstration.")

    def handle(self, *args: Any, **o: Any) -> None:
        try:
            check_allowed(profil="recette")
        except SeedRefused as exc:
            raise CommandError(str(exc)) from exc

        if o["reset"]:
            call_command("seed_realiste", reset=True, graine=o["graine"], stdout=self.stdout)
            call_command("seed_demo", reset=True, stdout=self.stdout)
            self.stdout.write(self.style.SUCCESS("Données de test retirées (les données réelles restent)."))
            return

        call_command("seed_prod", hors_ligne=o["hors_ligne"], stdout=self.stdout)

        self.stdout.write(self.style.MIGRATE_HEADING("▸ Personnes de démonstration"))
        call_command("seed_demo", stdout=self.stdout)

        if not o["hors_ligne"]:
            self.stdout.write(self.style.MIGRATE_HEADING("▸ Médias libres du manifeste"))
            try:
                call_command("fetch_seed_assets", profil="recette", stdout=self.stdout)
            except Exception as exc:  # noqa: BLE001 — un média injoignable ne bloque pas la recette
                self.stdout.write(self.style.WARNING(f"  téléchargement incomplet : {exc}"))

        folder = None if o["sans_musique"] else self._musique_demo()
        self.stdout.write(self.style.MIGRATE_HEADING("▸ Données de test"))
        call_command(
            "seed_realiste", profil="recette", echelle=o["echelle"], graine=o["graine"],
            medias="complets" if folder else "legers", medias_dossier=folder,
            hors_ligne=o["hors_ligne"], verifier=True, stdout=self.stdout,
        )  # fmt: skip
        self.stdout.write(self.style.SUCCESS("seed_recette terminé."))

    def _musique_demo(self) -> str | None:
        from apps.core.management.commands.seed_realiste import Command as SeedRealiste

        self.stdout.write(self.style.MIGRATE_HEADING("▸ Musique de démo"))
        try:
            command = SeedRealiste()
            command.stdout = self.stdout
            return command._musique_demo("recette")
        except CommandError as exc:
            self.stdout.write(self.style.WARNING(f"  {exc} Médias légers à la place."))
            return None
