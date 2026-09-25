"""Audit de provenance des textes du chapelet (plan L7) : liste ce qui n'a pas de source."""

from django.core.management.base import BaseCommand

from apps.rosary.models import Mystery, Prayer


class Command(BaseCommand):
    help = "Liste les méditations et prières sans provenance renseignée (code de sortie 1 s'il y en a)."

    def handle(self, *args, **options) -> None:
        mysteries = Mystery.objects.exclude(meditation__isnull=True).exclude(meditation="").filter(meditation_source="")
        prayers = Prayer.objects.filter(source="")
        for mystery in mysteries.select_related("group").order_by("group__name", "order"):
            self.stdout.write(f"Méditation sans source : {mystery.group.name} — {mystery.order}. {mystery.title}")
        for prayer in prayers.order_by("type", "language"):
            self.stdout.write(f"Prière sans source : {prayer.get_type_display()} ({prayer.language})")
        missing = mysteries.count() + prayers.count()
        if missing:
            self.stderr.write(self.style.WARNING(f"{missing} texte(s) sans provenance."))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("Tous les textes ont une provenance."))
