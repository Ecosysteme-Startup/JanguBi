from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.liturgy.tasks import bulk_import_task


class Command(BaseCommand):
    help = "Trigger a bulk import of AELF Liturgy data for a date range."

    def add_arguments(self, parser):
        parser.add_argument(
            "--start",
            type=str,
            required=True,
            help="Start date (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--end",
            type=str,
            required=True,
            help="End date (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--zones",
            nargs="+",
            default=None,
            help="Zones (ex. afrique romain france). Par défaut : LITURGY_ZONE, la zone servie par l'API.",
        )

    def handle(self, *args, **options):
        start_date = options["start"]
        end_date = options["end"]
        # Sans --zones, on importe la zone que l'API sert : sinon les lectures restent introuvables.
        zones = options["zones"] or [settings.LITURGY_ZONE]

        # Validate format roughly
        try:
            date.fromisoformat(start_date)
            date.fromisoformat(end_date)
        except ValueError:
            self.stdout.write(self.style.ERROR("Invalid date format. Please use YYYY-MM-DD."))
            return

        self.stdout.write(self.style.SUCCESS(f"Starting bulk import from {start_date} to {end_date} for zones {zones}"))

        # Dispatch the Celery task
        # It handles the delta looping internally
        bulk_import_task.delay(start_date, end_date, zones)

        self.stdout.write(self.style.SUCCESS("Bulk import tasks have been queued to Celery! Check logs for progress."))
