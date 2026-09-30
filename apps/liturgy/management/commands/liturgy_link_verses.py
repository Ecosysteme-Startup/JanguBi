from django.core.management.base import BaseCommand

from apps.liturgy.services import readings_link_verses


class Command(BaseCommand):
    help = "Rattache les lectures du jour aux versets de la Bible locale (après un import de la Bible)."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Recalculer aussi les lectures déjà rattachées.")

    def handle(self, *args, **options):
        linked = readings_link_verses(only_missing=not options["all"])
        self.stdout.write(self.style.SUCCESS(f"{linked} lecture(s) rattachée(s) à la Bible locale."))
