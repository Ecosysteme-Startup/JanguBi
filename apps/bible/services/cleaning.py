import html
import re


class CleaningService:
    """Service to clean and normalize Bible text and book names."""

    @staticmethod
    def strip_control_chars(text: str) -> str:
        """Removes unprintable control characters."""
        if not text:
            return text
        # Remove ASCII control characters except newline and tab
        return re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]", "", text)

    @staticmethod
    def clean_text(raw: str) -> str:
        """Cleans verse text: double-escaped unicodes, HTML entities, whitespace."""
        if not raw:
            return ""

        # Step 1: Decode unicode escapes if any (e.g. \u0027)
        # Note: json.load usually handles this, but if the data is double-escaped
        # we might need to handle it. For safety, we can attempt an encode/decode pass.
        try:
            # If it's a raw string containing literal \uXXXX sequences not handled by json parser
            if r"\u" in raw:
                raw = raw.encode("utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            pass

        # Step 2: Unescape HTML entities (e.g. &amp;, &apos;)
        text = html.unescape(raw)

        # Step 3: Strip control chars
        text = CleaningService.strip_control_chars(text)

        # Step 4: Normalize spaces: replace multiple spaces, tabs, newlines with single space
        text = re.sub(r"\s+", " ", text).strip()

        # Step 5: Normalize apostrophes to standard right single quotation mark
        # Some texts use standard apostrophe ('), others use curly right single quote (\u2019)
        # We will normalize to standard apostrophe to facilitate search, but both are acceptable.
        # Format A has "l\u2019obscurit\u00e9", Format B has "l'homme"
        text = text.replace("\u2019", "'").replace("`", "'")

        return text

    @staticmethod
    def normalize_book_name(name: str) -> str:
        """Normalizes book names for matching (lowercase, no extra spaces)."""
        if not name:
            return ""
        name = name.strip().lower()
        name = re.sub(r"\s+", " ", name)
        # Optionally, remove accents for even more robust matching
        import unicodedata

        name = "".join(c for c in unicodedata.normalize("NFD", name) if unicodedata.category(c) != "Mn")
        return name
