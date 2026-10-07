"""Réconciliation Keycloak ↔ application (docs/ADMIN-KEYCLOAK.md).

manage.py sync_keycloak --dry-run      # rapport seulement
manage.py sync_keycloak                # corrige les écarts
manage.py sync_keycloak --dry-run --json
"""

import json

from django.core.management.base import BaseCommand, CommandError

from apps.users.services_keycloak_sync import keycloak_reconcile


class Command(BaseCommand):
    help = "Détecte (et corrige, sans --dry-run) les écarts entre Keycloak et l'application."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Rapport seulement, aucune correction.")
        parser.add_argument("--json", action="store_true", help="Rapport complet au format JSON.")

    def handle(self, *args, dry_run: bool = False, json: bool = False, **options):  # noqa: A002
        run = keycloak_reconcile(dry_run=dry_run, trigger="commande")
        if run.error:
            raise CommandError(f"Réconciliation impossible : {run.error}")
        if json:
            self.stdout.write(
                _dumps({"id": run.pk, "dry_run": run.dry_run, "counts": run.counts, "report": run.report})
            )
            return
        mode = "SIMULATION" if dry_run else "CORRECTION"
        self.stdout.write(f"{mode} — réconciliation n° {run.pk}")
        for key, value in sorted(run.counts.items()):
            self.stdout.write(f"  {key:<28} {value}")
        for ecart in run.report:
            self.stdout.write(
                f"  - {ecart['kind']:<24} {ecart['email']:<32} {','.join(ecart['fields']) or '-':<30} → {ecart['correction']}"
            )
        style = self.style.SUCCESS if run.success else self.style.WARNING
        self.stdout.write(style("Terminé." if run.success else "Terminé avec des erreurs."))


def _dumps(data):
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)
