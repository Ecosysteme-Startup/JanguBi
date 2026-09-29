from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.core.exceptions import ApplicationError
from apps.hierarchy.imports import nodes_import_csv, places_import_csv


class Command(BaseCommand):
    help = "Importe des nœuds ou des lieux de culte depuis un CSV. Simulation par défaut ; --apply pour écrire."

    def add_arguments(self, parser):
        parser.add_argument("kind", choices=["nodes", "places"])
        parser.add_argument("path")
        parser.add_argument("--apply", action="store_true", help="Écrire en base (sinon simulation)")

    def handle(self, *args, kind: str, path: str, apply: bool, **options):
        content = Path(path).read_text(encoding="utf-8")
        importer = nodes_import_csv if kind == "nodes" else places_import_csv
        try:
            report = importer(content=content, dry_run=not apply)
        except ApplicationError as exc:
            raise CommandError(exc.message) from exc
        for line in report.lines:
            style = self.style.SUCCESS if line.status == "ok" else self.style.ERROR
            self.stdout.write(style(f"ligne {line.line} : {line.status} — {line.message} {line.code}"))
        verdict = "appliqué" if report.applied else ("simulation" if report.dry_run else "annulé (erreurs)")
        self.stdout.write(f"{report.valid} valides, {report.errors} erreurs — {verdict}.")
        if report.errors:
            raise CommandError("Import en erreur.")
