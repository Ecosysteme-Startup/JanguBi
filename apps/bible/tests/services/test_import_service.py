from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase

from apps.bible.models import Book, Testament, Verse
from apps.bible.services.import_service import ImportService


class ImportServiceTests(TestCase):
    def setUp(self):
        # The ImportService __init__ will automatically create testaments.
        self.service = ImportService()
        self.fixtures_dir = Path(settings.BASE_DIR) / "apps" / "bible" / "tests" / "fixtures"
        self.format_a_path = str(self.fixtures_dir / "mini_bible_format_a.json")
        self.format_b_path = str(self.fixtures_dir / "mini_bible_format_b.json")

    def test_ensure_testaments_created(self):
        # ImportService creates the three testaments: ancien, nouveau, psaume.
        self.assertEqual(Testament.objects.count(), 3)
        self.assertTrue(Testament.objects.filter(slug="ancien").exists())
        self.assertTrue(Testament.objects.filter(slug="nouveau").exists())
        self.assertTrue(Testament.objects.filter(slug="psaume").exists())

    def test_resolve_book_info_exact_match(self):
        canonical, testament, order, aliases = self.service.resolve_book_info("Genèse")
        self.assertEqual(canonical, "Genèse")
        self.assertEqual(testament.slug, "ancien")
        self.assertEqual(order, 1)

    def test_resolve_book_info_alias_case_insensitive(self):
        canonical, testament, order, aliases = self.service.resolve_book_info("  gEneSiS  ")
        self.assertEqual(canonical, "Genèse")
        self.assertEqual(testament.slug, "ancien")

    def test_resolve_book_info_psalms_heuristic(self):
        canonical, testament, order, aliases = self.service.resolve_book_info("Psaume de David 1")
        self.assertEqual(canonical, "Psaumes")
        # Psalms map to their own dedicated 'psaume' testament.
        self.assertEqual(testament.slug, "psaume")

    def test_resolve_book_info_unknown_fallback(self):
        canonical, testament, order, aliases = self.service.resolve_book_info("UnknownBook")
        self.assertEqual(canonical, "UnknownBook")
        self.assertEqual(testament.slug, "ancien")
        self.assertEqual(order, 999)

    @patch("apps.bible.services.import_service.populate_tsv_task.delay")
    def test_import_format_a(self, mock_tsv):
        self.service.import_file(self.format_a_path, "FRC97")

        # In mini_bible_format_a.json:
        # AT: 1 book (Genèse) -> 2 chapters -> 3 verses, 2 verses = 5 verses
        # NT: 1 book (Exode/Jean) -> 1 chapter -> 3 verses
        self.assertEqual(Book.objects.count(), 2)

        # Check first book
        genese = Book.objects.get(name="Genèse")
        self.assertEqual(genese.chapters.count(), 2)
        self.assertEqual(genese.verse_count, 5)

        # Check a specific verse
        ch1 = genese.chapters.get(number=1)
        v1 = ch1.verses.get(number=1)
        self.assertEqual(v1.text, "Au commencement Dieu créa le ciel et la terre.")
        self.assertIsNone(v1.original_id)  # Format A first verse lacks ID
        self.assertEqual(v1.source_file, "FRC97")

        v2 = ch1.verses.get(number=2)
        self.assertEqual(v2.original_id, 2)

        # The TSV indexing task is always enqueued per imported book.
        mock_tsv.assert_called()

    @patch("apps.bible.services.import_service.populate_tsv_task.delay")
    def test_import_format_b_skips_empty_verses(self, mock_tsv):
        self.service.import_file(self.format_b_path, "FreSynodale1921")

        # In mini_bible_format_b.json:
        # Genesis has 2 verses but both are empty text
        # Psalms has 3 verses with text
        self.assertEqual(Book.objects.count(), 2)

        psalms = Book.objects.get(name="Psaumes")
        self.assertEqual(psalms.verse_count, 3)
        self.assertEqual(psalms.testament.slug, "psaume")

        genese = Book.objects.get(name="Genèse")
        # Empty verses should have been skipped
        self.assertEqual(genese.verse_count, 0)
        self.assertEqual(genese.chapters.first().verses.count(), 0)

    @patch("apps.bible.services.import_service.populate_tsv_task.delay")
    def test_import_replaces_existing_source(self, mock_tsv):
        # Import once
        self.service.import_file(self.format_b_path, "FreSynodale1921")
        initial_verses = Verse.objects.count()

        # Import again with SAME source
        self.service.import_file(self.format_b_path, "FreSynodale1921")
        self.assertEqual(Verse.objects.count(), initial_verses)
