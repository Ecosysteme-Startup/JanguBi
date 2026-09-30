"""Données de test réalistes (plan des données de test) : une seule commande pour un monde crédible,
reproductible (graine) et réversible (``--reset``), jamais en production.

    SEED_ALLOWED=true python manage.py seed_realiste --profil local --echelle petite --medias legers --verifier

Orchestrateur seulement : chaque application fournit ses semeurs (``apps/<app>/seeders.py``), découverts
et ordonnés par le registre (``apps.core.seeding.registry``). Voir ``docs/DONNEES-DE-TEST.md``.
"""

from __future__ import annotations

import pathlib
import re
import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.core.seeding import registry
from apps.core.seeding.context import MEDIAS, SCALES, SeedContext
from apps.core.seeding.guards import SeedRefused, check_allowed, tasks_muted

# Tâches autorisées pendant le semis : l'encodage réel des pistes (``--medias complets``).
ALLOWED_TASKS = ("apps.audio.tasks.audio_transcode_task",)


def _duration(value: str) -> int:
    match = re.fullmatch(r"(\d+)\s*(s|min|m|h)?", value.strip())
    if not match:
        raise CommandError("Durée invalide (ex. 10min, 90s, 1h).")
    n, unit = int(match.group(1)), match.group(2) or "min"
    return n * {"s": 1, "min": 60, "m": 60, "h": 3600}[unit]


class Command(BaseCommand):
    help = "Remplit une base locale ou de recette avec des données de test réalistes (jamais en production)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--profil", choices=["local", "recette"], default="local")
        parser.add_argument("--echelle", choices=list(SCALES), default="petite")
        parser.add_argument("--graine", type=int, default=2026)
        parser.add_argument("--modules", default="tous", help="tous, ou liste : socle,dons,vie,audio,parole…")
        parser.add_argument("--medias", choices=MEDIAS, default="legers")
        parser.add_argument("--historique", type=int, default=12, help="Mois d'historique (dons, écoutes).")
        parser.add_argument("--reset", action="store_true", help="Supprime exactement le lot de cette graine.")
        parser.add_argument("--verifier", action="store_true", help="Contrôle les invariants et affiche le rapport.")
        parser.add_argument("--simuler-trafic", dest="trafic", default=None, help="Ex. 10min : dons et écoutes en continu.")
        parser.add_argument("--medias-dossier", dest="medias_dossier", default=None,
                            help="Album libre fourni (jamais commité) ; credits.yaml optionnel dans ce dossier.")  # fmt: skip
        parser.add_argument("--musique-demo", dest="musique_demo", action="store_true",
                            help="Album = musique de démo : seed_assets/musique-demo/, sinon seed-assets/ du bucket de l'app.")  # fmt: skip
        parser.add_argument("--bible-json", dest="bible_json", default=None,
                            help="JSON de la Bible (AELF) à importer par import_bible si la Bible est absente.")  # fmt: skip
        parser.add_argument("--bible-source", dest="bible_source", default="AELF")
        parser.add_argument("--piper-voix", dest="piper_voix", default=None, help="Modèle de voix Piper (.onnx).")
        parser.add_argument("--hors-ligne", dest="hors_ligne", action="store_true",
                            help="Aucun appel réseau (AELF, Keycloak) : replis directs.")  # fmt: skip

    def handle(self, *args: Any, **o: Any) -> None:
        try:
            check_allowed(profil=o["profil"])
        except SeedRefused as exc:
            raise CommandError(str(exc)) from exc
        if o["musique_demo"]:
            o["medias_dossier"] = self._musique_demo(o["profil"])
        registry.autodiscover()
        ctx = SeedContext(
            profil=o["profil"], scale=SCALES[o["echelle"]], graine=o["graine"], medias=o["medias"],
            historique=max(1, min(o["historique"], 13)), medias_dossier=o["medias_dossier"],
            bible_json=o["bible_json"], bible_source=o["bible_source"], piper_voix=o["piper_voix"],
            reseau=not o["hors_ligne"], stdout=self.stdout,
        )  # fmt: skip
        if o["reset"]:
            self._reset(ctx)
            return
        selected = None if o["modules"] in ("tous", "") else {m.strip() for m in o["modules"].split(",") if m.strip()}
        try:
            seeders = registry.ordered(selected)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self._check_single_batch(ctx)
        started = time.monotonic()
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"seed_realiste — profil {ctx.profil}, échelle {ctx.scale.code}, graine {ctx.graine}, "
                f"médias {ctx.medias}, lot « {ctx.batch} »"
            )
        )
        with tasks_muted(allow=ALLOWED_TASKS if ctx.medias == "complets" else ()) as dropped:
            for seeder in seeders:
                ctx.current_seeder = seeder.name
                if not seeder.always and ctx.done(seeder.name):
                    self.stdout.write(f"- {seeder.name} : déjà semé (lot {ctx.batch}), rien à ajouter")
                    continue
                t0 = time.monotonic()
                self.stdout.write(f"- {seeder.name} …")
                result = seeder.seed(ctx)
                if not seeder.always:
                    ctx.mark_done(seeder.name)
                summary = ", ".join(f"{k} {v}" for k, v in (result or {}).items())
                self.stdout.write(f"  {seeder.name} : {summary} ({time.monotonic() - t0:.1f} s)")
        if dropped:
            self.stdout.write(f"  {len(dropped)} tâche(s) non envoyée(s) pendant le semis (push, e-mails…).")
        elapsed = time.monotonic() - started
        self.stdout.write(self.style.SUCCESS(f"Semis terminé en {elapsed:.1f} s."))
        failures = 0
        if o["verifier"]:
            failures = self._verify(ctx, registry.ordered(None))
        if ctx.notes:
            self.stdout.write(self.style.MIGRATE_HEADING("Remarques"))
            for note in ctx.notes:
                self.stdout.write(f"  - {note}")
        if o["trafic"]:
            from apps.core.seeding.traffic import simulate

            simulate(ctx, seconds=_duration(o["trafic"]))
        if failures:
            raise CommandError(f"{failures} invariant(s) en échec.")

    def _check_single_batch(self, ctx: SeedContext) -> None:
        from apps.core.models import SeedRecord

        others = set(SeedRecord.objects.exclude(batch=ctx.batch).values_list("batch", flat=True).distinct())
        if others:
            raise CommandError(
                f"Un autre lot est présent ({', '.join(sorted(others))}) : un seul lot à la fois. "
                "Lancez d'abord --reset avec sa graine."
            )

    def _verify(self, ctx: SeedContext, seeders: list[registry.Seeder]) -> int:
        self.stdout.write(self.style.MIGRATE_HEADING("Vérification"))
        failures = 0
        for seeder in seeders:
            if not ctx.done(seeder.name) and not seeder.always:
                continue
            for check in seeder.verify(ctx):
                mark = self.style.SUCCESS("OK   ") if check.ok else self.style.ERROR("ÉCHEC")
                self.stdout.write(f"  {mark} [{seeder.name}] {check.label} — {check.detail}")
                failures += 0 if check.ok else 1
        return failures

    def _musique_demo(self, profil: str) -> str:
        """Dossier de la musique de démo : ``seed_assets/musique-demo/`` s'il est prêt, sinon le bucket."""
        from django.conf import settings

        from apps.audio.seed_medias import DEMO_PREFIX, cache_dir, restore_folder, store_for

        local = pathlib.Path(settings.BASE_DIR) / "seed_assets" / DEMO_PREFIX
        if (local / "credits.yaml").exists():
            return str(local)
        store = store_for(profil)
        folder = restore_folder(store, cache_dir() / DEMO_PREFIX)
        if folder is None:
            raise CommandError(
                f"Musique de démo introuvable ({local}, {store.kind}). "
                "Lancez d'abord prepare_musique_demo (--publier en recette)."
            )
        self.stdout.write(f"Musique de démo reprise depuis {store.kind}.")
        return str(folder)

    def _reset(self, ctx: SeedContext) -> None:
        from apps.core.models import SeedRecord

        seeders = registry.ordered(None)
        self.stdout.write(self.style.MIGRATE_HEADING(f"Remise à zéro du lot « {ctx.batch} »"))
        with tasks_muted():
            for seeder in reversed(seeders):
                ctx.current_seeder = seeder.name
                result = seeder.reset(ctx)
                if result:
                    self.stdout.write(f"- {seeder.name} : " + ", ".join(f"{k} {v}" for k, v in result.items()))
        n, _ = SeedRecord.objects.filter(batch=ctx.batch).delete()
        self.stdout.write(self.style.SUCCESS(f"Lot « {ctx.batch} » supprimé ({n} trace(s))."))
