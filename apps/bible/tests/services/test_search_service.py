from django.db import connection
from django.test import TransactionTestCase

from apps.bible.models import Book, Chapter, Testament, Verse
from apps.bible.services.search_service import SearchService


class SearchServiceTests(TransactionTestCase):
    # TransactionTestCase is needed to properly test raw SQL and vectors/tsv
    # if we are doing raw queries that fetch outside standard ORM transactions properly.

    def setUp(self):
        # Create test data
        t = Testament.objects.create(name="Ancien Testament", slug="ancien", order=1)
        b = Book.objects.create(name="Genèse", slug="genese", testament=t, order=1, verse_count=3)
        c = Chapter.objects.create(book=b, number=1, verse_count=3)

        Verse.objects.create(chapter=c, number=1, text="Au commencement, Dieu créa les cieux et la terre.")
        Verse.objects.create(chapter=c, number=2, text="La terre était informe et vide: il y avait des ténèbres.")
        Verse.objects.create(chapter=c, number=3, text="Dieu dit: Que la lumière soit! Et la lumière fut.")

        # Second book for testing testament/book filtering
        t2 = Testament.objects.create(name="Nouveau Testament", slug="nouveau", order=2)
        b2 = Book.objects.create(name="Jean", slug="jean", testament=t2, order=2, verse_count=2)
        c2 = Chapter.objects.create(book=b2, number=1, verse_count=2)
        Verse.objects.create(
            chapter=c2, number=1, text="Au commencement était la Parole, et la Parole était avec Dieu."
        )
        Verse.objects.create(chapter=c2, number=2, text="En elle était la vie, et la vie était la lumière des hommes.")

        # Populate TSV vector for testing raw SQL search
        with connection.cursor() as cursor:
            cursor.execute("UPDATE bible_verse SET tsv = to_tsvector('fr_unaccent', text);")

        self.service = SearchService()

    def test_lexical_search_basic(self):
        # Search "lumière"
        results = self.service.search("lumière", source_file=None)

        # We expect 2 matches grouped in 2 books (Genèse and Jean)
        self.assertEqual(len(results), 2, "Should find matches in both Genèse and Jean")

        # First result should be Genèse due to order
        self.assertEqual(results[0]["book"]["name"], "Genèse")
        self.assertEqual(len(results[0]["matches"]), 1)
        self.assertEqual(results[0]["matches"][0]["verse"]["number"], 3)
        self.assertIn("lumière", results[0]["matches"][0]["verse"]["text"])

        # Second result should be Jean
        self.assertEqual(results[1]["book"]["name"], "Jean")
        self.assertEqual(len(results[1]["matches"]), 1)
        self.assertEqual(results[1]["matches"][0]["verse"]["number"], 2)

    def test_search_ignores_accents(self):
        # « lumiere » sans accent trouve « lumière » (configuration fr_unaccent, ADR-018).
        results = self.service.search("lumiere", source_file=None)

        self.assertEqual([r["book"]["name"] for r in results], ["Genèse", "Jean"])

    def test_search_tolerates_a_typo_through_trigrams(self):
        # « comencement » (faute) : le plein texte ne trouve rien, le repli trigramme si.
        results = self.service.search("comencement", source_file=None)

        self.assertEqual({r["book"]["name"] for r in results}, {"Genèse", "Jean"})

    def test_typo_fallback_leaves_the_trigram_threshold_untouched(self):
        # Le seuil abaissé du repli ne doit pas fuir vers les recherches trigrammes suivantes.
        from django.db import transaction

        with transaction.atomic():  # comme sous ATOMIC_REQUESTS
            with connection.cursor() as cursor:
                cursor.execute("SHOW pg_trgm.similarity_threshold")
                before = cursor.fetchone()[0]
            self.service.search("comencement", source_file=None)
            with connection.cursor() as cursor:
                cursor.execute("SHOW pg_trgm.similarity_threshold")
                after = cursor.fetchone()[0]

        self.assertEqual(after, before)

    def test_lexical_search_with_testament_filter(self):
        # Search "commencement", which is in both Genesis 1:1 and Jean 1:1
        all_results = self.service.search("commencement", source_file=None)
        self.assertEqual(len(all_results), 2)

        # Filter AT
        at_results = self.service.search("commencement", testament_slug="ancien", source_file=None)
        self.assertEqual(len(at_results), 1)
        self.assertEqual(at_results[0]["book"]["name"], "Genèse")

        # Filter NT
        nt_results = self.service.search("commencement", testament_slug="nouveau", source_file=None)
        self.assertEqual(len(nt_results), 1)
        self.assertEqual(nt_results[0]["book"]["name"], "Jean")

    def test_lexical_search_no_results(self):
        results = self.service.search("xyznonexistent", source_file=None)
        self.assertEqual(results, [])

    def test_lexical_search_respects_limit(self):
        # Search "Dieu", present in Gen 1:1, Gen 1:3, Jean 1:1. Total 3 matches.
        results = self.service.search("Dieu", limit=1, source_file=None)
        # Grouped structure, so we need to count total matches inside
        total_matches = sum(len(group["matches"]) for group in results)
        self.assertEqual(total_matches, 1)

    def test_search_group_by_book(self):
        # Check structure
        results = self.service.search("Dieu", source_file=None)
        # Ensure it's grouped properly
        for group in results:
            self.assertIn("book", group)
            self.assertIn("matches", group)
            self.assertIsInstance(group["matches"], list)
            for m in group["matches"]:
                self.assertIn("verse", m)
                self.assertIn("score", m)
                self.assertIn("no_internal_source", m)

    def test_search_no_internal_source_flag(self):
        # This is hard to trigger exactly without mocking the inner lexical_search,
        # so we will use a word that might yield a very low rank, or we mock
        # _lexical_search for a specific result.

        # First let's check normal. "Terre"
        results = self.service.search("terre", source_file=None)
        self.assertTrue(len(results) > 0)

        # Let's mock the internal lexical_search to force a low score
        import unittest.mock as mock

        with mock.patch.object(
            self.service,
            "_lexical_search",
            return_value=[
                {
                    "id": 99,
                    "chapter_id": 1,
                    "verse_number": 1,
                    "text": "...",
                    "chapter_number": 1,
                    "book_id": 1,
                    "book_name": "Test",
                    "book_slug": "test",
                    "book_order": 1,
                    "testament_slug": "ancien",
                    "score": 0.05,  # low score
                    "no_internal_source": True,
                }
            ],
        ):
            flagged_results = self.service.search("mocked")
            m = flagged_results[0]["matches"][0]
            self.assertTrue(m["no_internal_source"])

    def test_hybrid_flag_is_ignored_and_search_stays_lexical(self):
        # Plus de recherche vectorielle (ADR-018) : le drapeau des anciens clients est sans effet.
        import unittest.mock as mock

        with mock.patch.object(self.service, "_lexical_search", return_value=[]) as mock_lexical:
            self.service.search("test", use_hybrid=True)
            mock_lexical.assert_called_once()
