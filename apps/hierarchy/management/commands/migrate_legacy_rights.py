from pathlib import Path

from django.core.management.base import BaseCommand

from apps.hierarchy.legacy_rights import legacy_rights_apply, legacy_rights_plan, plan_to_csv


class Command(BaseCommand):
    help = (
        "Convertit les droits de l'ancien modèle (RoleAssignment, doyens, pastoral_role, appartenance) "
        "en nominations. Par défaut : écrit seulement le rapport CSV. --apply pour appliquer."
    )

    def add_arguments(self, parser):
        parser.add_argument("--report", default="legacy-rights-plan.csv", help="Chemin du rapport CSV")
        parser.add_argument("--apply", action="store_true", help="Appliquer le plan (après validation humaine)")

    def handle(self, *args, report: str, apply: bool, **options):
        rows = legacy_rights_plan()
        Path(report).write_text(plan_to_csv(rows), encoding="utf-8")
        by_action: dict[str, int] = {}
        for row in rows:
            by_action[row.action] = by_action.get(row.action, 0) + 1
        self.stdout.write(f"Rapport : {report} — " + ", ".join(f"{k} : {v}" for k, v in sorted(by_action.items())))
        if not apply:
            self.stdout.write(self.style.WARNING("Simulation : rien n'a été écrit. Relire le rapport puis relancer avec --apply."))
            return
        counts = legacy_rights_apply(rows=rows)
        self.stdout.write(self.style.SUCCESS(f"Appliqué : {counts}"))
