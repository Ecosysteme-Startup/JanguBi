"""Données réelles, communes à la production et à la recette. Idempotent : relançable sans risque.

    python manage.py seed_prod                 # référentiel, Bible, Rosaire, liturgie des 7 prochains jours
    python manage.py seed_prod --jours 30      # liturgie sur 30 jours
    python manage.py seed_prod --hors-ligne    # sans appel à AELF (liturgie sautée)

Rien de fictif ici : référentiel territorial (profil ``senegal``), Bible (importée seulement si absente),
mystères du Rosaire, lectures du jour AELF rattachées aux versets. Les données de démonstration et de test
sont dans ``seed_recette``.
"""

from __future__ import annotations

import datetime
import pathlib
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandParser

BIBLE_JSON = pathlib.Path(settings.BASE_DIR) / "init" / "bibles" / "format" / "json" / "bible-fr-aelf.json"


class Command(BaseCommand):
    help = "Données réelles (référentiel, Bible, Rosaire, liturgie) : production et recette. Idempotent."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--profil-territoire", dest="territoire", default="senegal")
        parser.add_argument("--bible-json", dest="bible_json", default=str(BIBLE_JSON))
        parser.add_argument("--bible-source", dest="bible_source", default=settings.BIBLE_EDITION or "AELF")
        parser.add_argument("--jours", type=int, default=7, help="Jours de liturgie AELF à importer (dès aujourd'hui).")
        parser.add_argument("--hors-ligne", dest="hors_ligne", action="store_true", help="Sans appel à AELF.")

    def handle(self, *args: Any, **o: Any) -> None:
        self._step("Référentiel territorial")
        call_command("seed_hierarchy_profile", o["territoire"], stdout=self.stdout)

        self._step("Bible")
        from apps.bible.seeders import bible_present

        if bible_present():
            self.stdout.write("  déjà importée")
        else:
            call_command("import_bible", o["bible_json"], source=o["bible_source"], stdout=self.stdout)

        self._step("Rosaire")
        call_command("seed_rosary", stdout=self.stdout)

        self._step("Liturgie du jour (AELF)")
        if o["hors_ligne"]:
            self.stdout.write("  sautée (--hors-ligne)")
        else:
            self._liturgy(max(1, o["jours"]))

        from apps.liturgy.services import readings_link_verses

        linked = readings_link_verses()
        self.stdout.write(f"  {linked} lecture(s) rattachée(s) aux versets")
        self.stdout.write(self.style.SUCCESS("seed_prod terminé."))

    def _liturgy(self, jours: int) -> None:
        from apps.liturgy.models import Reading
        from apps.liturgy.tasks import daily_sync_task

        zone = settings.LITURGY_ZONE
        today = datetime.date.today()
        days = [today + datetime.timedelta(days=offset) for offset in range(jours)]
        for day in days:
            # Synchrone : les lectures doivent exister avant leur rattachement aux versets.
            daily_sync_task.apply(args=[day.isoformat(), [zone]])
        served = set(
            Reading.objects.filter(liturgical_date__zone=zone, liturgical_date__date__in=days)
            .values_list("liturgical_date__date", flat=True)
        )
        self.stdout.write(f"  {len(served)}/{jours} jour(s) avec lectures, zone {zone}")
        if len(served) < jours:
            self.stdout.write(self.style.WARNING("  AELF injoignable pour certains jours : relancer seed_prod plus tard."))

    def _step(self, label: str) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING(f"▸ {label}"))
