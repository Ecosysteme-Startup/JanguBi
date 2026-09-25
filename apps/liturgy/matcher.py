import re
from typing import List

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
        if cls._books_cache is None:
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

        # 3. Parse chapter and verses
        # Typically formatted as <Chapter>, <Verses>
        # Or just <Chapter> if whole chapter.
        # Handle Psalm numbering quirk: Ps 15 (16) -> mostly we care about 16 for liturgical text or 15 for Heb.
        # Let's clean out the parenthesis first for Psalms by taking the first number
        parts = numbers_part.split(",", 1)  # Only split on the FIRST comma
        if len(parts) < 2:
            return [] # Too complex to parse without chapter/verse separator
            
        chapter_str = parts[0].strip()
        verses_str = parts[1].strip()
        
        # Extract the integer chapter (ignoring parentheses like in Psalms)
        chapter_match = re.search(r"(\d+)", chapter_str)
        if not chapter_match:
            return []
        chapter_num = int(chapter_match.group(1))
        
        # 4. Parse verses like "51-62" or "1-2a.5" or "5a.8,9"
        # We'll replace non-numeric sequence seperators like ',' and '.' with spaces
        # and extract all integers to create a bounding range.
        clean_verses_str = verses_str.replace(",", " ").replace(".", " ")
        verse_numbers = [int(n) for n in re.findall(r"\d+", clean_verses_str)]
        if not verse_numbers:
            return []
            
        min_v = min(verse_numbers)
        max_v = max(verse_numbers)

        # 5. Bring it together into a Verse QuerySet
        qs = edition_filter(
            Verse.objects.filter(
                chapter__book=matched_book,
                chapter__number=chapter_num,
                number__gte=min_v,
                number__lte=max_v,
            )
        ).order_by("number")
        
        return list(qs)
