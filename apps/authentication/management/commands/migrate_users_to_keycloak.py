from collections import Counter

from django.core.management.base import BaseCommand

from apps.authentication.services_keycloak import users_to_keycloak_migrate


class Command(BaseCommand):
    help = (
        "Migre les comptes vers Keycloak en important les hachages pbkdf2_sha256 (aucune "
        "réinitialisation). Simulation par défaut ; --apply pour écrire dans Keycloak."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args, apply: bool, limit: int | None, **options):
        lines = users_to_keycloak_migrate(apply=apply, limit=limit)
        for line in lines:
            self.stdout.write(f"{line.email} : {line.action} (mot de passe : {line.password}) {line.keycloak_id}")
        summary = Counter((line.action, line.password) for line in lines)
        self.stdout.write(", ".join(f"{a}/{p} : {n}" for (a, p), n in sorted(summary.items())))
        if not apply:
            self.stdout.write(self.style.WARNING("Simulation : rien n'a été écrit. Relancer avec --apply."))
