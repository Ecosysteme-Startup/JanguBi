import re
from typing import List

from django.db.models import Q

from apps.bible.editions import edition_filter
from apps.bible.models import Book, Verse


class CitationMatcher:
    """
    Utility class to map AELF citations (e.g., '1 R 19, 16b. 19-21' or 'Ps 15 (16), 1-2a.5...' or 'Lc 9, 51-62')
    into a Django QuerySet of local `bible.Verse` objects.
    """

    _books_cache = None

    @classmethod
    def _get_books(cls) -> List[Book]:
        # Une liste vide n'est pas gardée : sinon un premier appel avant l'import de la Bible
        # bloquerait tout rattachement jusqu'au redémarrage du processus (worker Celery).
        if not cls._books_cache:
            # Load into memory once per worker process to avoid fetching on every match
            cls._books_cache = list(Book.objects.all())
        return cls._books_cache

    @classmethod
    def match(cls, citation: str) -> List[Verse]:
        """
        Attempts to parse a standard liturgical citation and fetch the corresponding verses locally.
        This is a best-effort matching strategy.
        Returns a list of Verse objects.
        """
        if not citation:
            return []
            
        # Clean citation
        citation = citation.strip()
        
        # 1. Very basic heuristic: extract the book abbreviation and chapters/verses.
        # This regex matches patterns like: "Lc 9, 51-62" or "Ps 15 (16), 1-2a.5"
        # Group 1: Book name/abbr (e.g. "Lc", "1 R", "Ps")
        # Group 2: Chapter(s) and Verse(s) part (e.g. "9, 51-62", "15 (16), 1-2a")
        match = re.search(r"^([1-4]?\s*[A-Za-zÉéÀà]+)\s+(.+)$", citation)
        if not match:
            return []
            
        book_part = match.group(1).strip()
        numbers_part = match.group(2).strip()
        
        # 2. Find the book
        # AELF uses abbreviations. We'll do an exact or fuzzy search on `slug` or `alt_names`
        # We lowercase and remove spaces for easier matching
        clean_book_part = book_part.lower().replace(" ", "")
        
        # Try to find a matching book locally
        books = cls._get_books()
        matched_book = None
        for b in books:
            if b.slug.startswith(clean_book_part):
                matched_book = b
                break
            # Check JSON alt_names array
            for alt in b.alt_names:
                if alt.lower().replace(" ", "").startswith(clean_book_part):
                    matched_book = b
                    break
            if matched_book:
                break
                
        if not matched_book:
            return []

        # 3. Parse chapter(s) and verses.
        # Une citation peut couvrir plusieurs chapitres, séparés par « ; » (changement de
        # chapitre/référence) : « Jb 38, 1.12-21 ; 40, 3-5 » = 38,1 ; 38,12-21 ; 40,3-5.
        # Chaque référence est « <chapitre>, <versets> » (quirk des Psaumes : « 15 (16) » →
        # on prend le premier nombre). Une référence sans virgule continue le chapitre courant
        # (versets supplémentaires) ou, faute de chapitre courant, vaut un chapitre entier.
        chapter_ranges: list[tuple[int, list[tuple[int, int]]]] = []
        current_chapter: int | None = None
        for reference in numbers_part.split(";"):
            reference = reference.strip()
            if not reference:
                continue
            if "," in reference:
                chapter_str, verses_str = reference.split(",", 1)
                chapter_match = re.search(r"(\d+)", chapter_str)
                if not chapter_match:
                    continue
                current_chapter = int(chapter_match.group(1))
                ranges = cls._parse_verse_ranges(verses_str)
            elif current_chapter is not None:
                # Suite de versets rattachée au chapitre courant (pas de nouvelle virgule).
                ranges = cls._parse_verse_ranges(reference)
            else:
                # Chapitre entier (pas de versets) : on ignore, trop large pour un rattachement fiable.
                continue
            if ranges:
                chapter_ranges.append((current_chapter, ranges))

        if not chapter_ranges:
            return []

        # 4. Bring it together into a Verse QuerySet (multi-chapitres éventuels).
        overall = Q()
        for chapter_num, ranges in chapter_ranges:
            in_ranges = Q()
            for low, high in ranges:
                in_ranges |= Q(number__gte=low, number__lte=high)
            overall |= Q(chapter__number=chapter_num) & in_ranges

        qs = edition_filter(
            Verse.objects.filter(overall, chapter__book=matched_book)
        ).order_by("chapter__number", "number")

        return list(qs)

    @staticmethod
    def _parse_verse_ranges(verses_str: str) -> list[tuple[int, int]]:
        """Plages de versets : « 1-12.14-16 », « 10bc-11, 12-13 », « 5a.8 ». Chaque segment
        (séparé par « . » ou « , ») est une plage « a-b » ou un verset seul ; les lettres
        (demi-versets) sont ignorées. On garde les trous (« 1-12.14-16 » exclut le verset 13)."""
        ranges: list[tuple[int, int]] = []
        for segment in re.split(r"[.,]", verses_str):
            bounds = [int(n) for n in re.findall(r"\d+", segment)]
            if bounds:
                ranges.append((min(bounds), max(bounds)))
        return ranges
