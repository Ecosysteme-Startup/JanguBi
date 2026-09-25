from django.core.management.base import BaseCommand, CommandError

from apps.core.exceptions import ApplicationError
from apps.hierarchy.seeding import hierarchy_profile_load


class Command(BaseCommand):
    help = "Charge un profil de hiérarchie (types, nœuds, lieux, horaires). Idempotent. Ex. : senegal"

    def add_arguments(self, parser):
        parser.add_argument("profile", help="Nom du profil (ex. senegal)")

    def handle(self, *args, profile: str, **options):
        try:
            report = hierarchy_profile_load(profile=profile)
        except ApplicationError as exc:
            raise CommandError(exc.message) from exc
        created = ", ".join(f"{k} : {v}" for k, v in report.created.items())
        self.stdout.write(self.style.SUCCESS(f"Profil « {profile} » chargé ({created} créés)."))
