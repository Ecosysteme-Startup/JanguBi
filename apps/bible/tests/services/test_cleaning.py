from django.test import TestCase

from apps.bible.services.cleaning import CleaningService


class CleaningServiceTests(TestCase):
    def test_clean_text_strips_whitespace(self):
        self.assertEqual(CleaningService.clean_text("  hello world  "), "hello world")

    def test_clean_text_normalizes_multiple_spaces(self):
        self.assertEqual(CleaningService.clean_text("hello   world"), "hello world")

    def test_clean_text_decodes_double_escaped_unicode(self):
        # We simulate a string containing literal \u sequence
        raw = r"l\u0027homme"
        self.assertEqual(CleaningService.clean_text(raw), "l'homme")

    def test_clean_text_html_unescape(self):
        self.assertEqual(CleaningService.clean_text("Dieu &amp; l&apos;homme"), "Dieu & l'homme")

    def test_clean_text_removes_control_chars(self):
        # \x00 is null, \x07 is bell. Both should be removed.
        self.assertEqual(CleaningService.clean_text("hello\x00world\x07"), "helloworld")

    def test_clean_text_normalizes_apostrophes(self):
        # \u2019 is the curly apostrophe
        self.assertEqual(CleaningService.clean_text("l\u2019homme"), "l'homme")

    def test_clean_text_preserves_punctuation(self):
        self.assertEqual(CleaningService.clean_text("Bonjour! «Ça va?»"), "Bonjour! «Ça va?»")

    def test_clean_text_empty_string(self):
        self.assertEqual(CleaningService.clean_text(""), "")

    def test_clean_text_real_verse(self):
        raw = "Au commencement Dieu cr\u00e9a le ciel et la terre."
        # Because we're writing a python string literal, \u00e9 is literally é in python.
        # But if we were to get r"cr\u00e9a" from json, it would decode it.
        # Here we just verify normal chars pass through.
        self.assertEqual(CleaningService.clean_text(raw), "Au commencement Dieu créa le ciel et la terre.")

    def test_strip_control_chars(self):
        self.assertEqual(CleaningService.strip_control_chars("\x01\x02texte\x1f"), "texte")

    def test_normalize_book_name(self):
        self.assertEqual(CleaningService.normalize_book_name("  genesis "), "genesis")
        self.assertEqual(CleaningService.normalize_book_name("Genèse"), "genese")
        # Ensure it works with 1 Samuel
        self.assertEqual(CleaningService.normalize_book_name("1 Samuel"), "1 samuel")
