from django.core.management.base import BaseCommand, CommandError

from apps.bible.models import Book, Verse
from apps.bible.services.import_service import ImportService


class Command(BaseCommand):
    help = "Imports a Bible JSON file (Format A or B)"

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str, help="Absolute path to the JSON file")
        parser.add_argument("--source", type=str, required=True, help="Source name (e.g. 'FRC97', 'FreSynodale1921')")

    def handle(self, *args, **options):
        file_path = options["file_path"]
        source = options["source"]

        self.stdout.write(self.style.NOTICE(f"Starting import of {file_path} as '{source}'..."))

        try:
            service = ImportService()
            service.import_file(file_path, source)

            # Print quick summary
            books = Book.objects.all().count()
            verses = Verse.objects.filter(source_file=source).count()

            self.stdout.write(self.style.SUCCESS(f"Successfully imported {verses} verses across {books} total books."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Import failed: {e}"))
            raise CommandError(str(e))
