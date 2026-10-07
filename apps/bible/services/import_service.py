import json
import logging
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml
from django.conf import settings
from django.db import transaction

from apps.bible.models import Book, Chapter, Testament, Verse
from apps.bible.services.cleaning import CleaningService
from apps.bible.tasks import populate_tsv_task

logger = logging.getLogger(__name__)


class ImportFormat(Enum):
    FORMAT_A = "format_a"  # Format typique de structuration par 'Testaments'
    FORMAT_B = "format_b"  # Format plat par 'books'


class ImportService:
    """Service to import Bible JSON files into the database."""

    def __init__(self):
        self._load_book_mapping()
        self._ensure_testaments()

    def _load_book_mapping(self):
        """Loads book definitions from mapping YAML."""
        mapping_path = Path(settings.BASE_DIR) / "apps" / "bible" / "data" / "book_mapping.yaml"
        with open(mapping_path, "r", encoding="utf-8") as f:
            self.mapping = yaml.safe_load(f)

        # Build quick lookup by alias (normalized)
        self.alias_to_canonical = {}
        for key, data in self.mapping.items():
            canonical = data["canonical_name"]
            normalized_canon = CleaningService.normalize_book_name(canonical)
            self.alias_to_canonical[normalized_canon] = canonical
            for alias in data.get("aliases", []):
                normalized_alias = CleaningService.normalize_book_name(alias)
                self.alias_to_canonical[normalized_alias] = canonical

    def _ensure_testaments(self):
        """Ensures all three Testaments exist in DB."""
        self.ancien_testament, _ = Testament.objects.get_or_create(
            slug="ancien", defaults={"name": "Ancien Testament", "order": 1}
        )
        self.nouveau_testament, _ = Testament.objects.get_or_create(
            slug="nouveau", defaults={"name": "Nouveau Testament", "order": 2}
        )
        self.psaumes_testament, _ = Testament.objects.get_or_create(
            slug="psaume", defaults={"name": "Psaumes", "order": 3}
        )

    def resolve_book_info(self, name_hint: str) -> Tuple[str, Testament, int, list]:
        """Resolves a raw name hint into DB canonical info."""
        normalized = CleaningService.normalize_book_name(name_hint)

        # Handle Psalms specific edge case from string formatting if needed
        if "psaume" in normalized or "psalm" in normalized:
            canonical = "Psaumes"
        else:
            canonical = self.alias_to_canonical.get(normalized)

        if canonical and canonical in self.mapping:
            data = self.mapping[canonical]
            testament_slug = data["testament"]
            if testament_slug == "nouveau":
                testament = self.nouveau_testament
            elif testament_slug == "psaume":
                testament = self.psaumes_testament
            else:
                testament = self.ancien_testament
            return canonical, testament, data["order"], data.get("aliases", [])

        # Fallback: create an unknown book at the end of Ancien Testament
        logger.warning(f"Could not resolve book name: '{name_hint}'. Using as-is.")
        return name_hint, self.ancien_testament, 999, []

    def get_or_create_book(self, raw_name: str) -> Book:
        canonical_name, testament, order, aliases = self.resolve_book_info(raw_name)

        book, created = Book.objects.get_or_create(
            name=canonical_name,
            defaults={
                "testament": testament,
                "order": order,
                "alt_names": aliases,
            },
        )

        if not created:
            update_fields = []
            if book.testament_id != testament.id:
                book.testament = testament
                update_fields.append("testament")
            if book.order != order:
                book.order = order
                update_fields.append("order")
            if aliases and book.alt_names != aliases:
                book.alt_names = aliases
                update_fields.append("alt_names")
            if update_fields:
                book.save(update_fields=update_fields)

        return book

    def import_file(self, file_path: str, source_name: str):
        """Main entry point to import a JSON file."""
        logger.info(f"Starting import from {file_path} as '{source_name}'")

        self._purge_source_data(source_name)

        with open(file_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)

        if "Testaments" in data:
            self._import_format_a(data, source_name)
        elif "books" in data:
            self._import_format_b(data, source_name)
        else:
            raise ValueError(f"Unknown JSON format in {file_path}")

        logger.info(f"Import from {source_name} complete.")

    def _purge_source_data(self, source_name: str):
        """Deletes all verses for a source, then prunes empty chapters/books."""
        with transaction.atomic():
            deleted_verses, _ = Verse.objects.filter(source_file=source_name).delete()

            deleted_chapters, _ = Chapter.objects.filter(verses__isnull=True).distinct().delete()
            deleted_books, _ = Book.objects.filter(chapters__isnull=True).distinct().delete()

        logger.info(
            "Purged source '%s': verses=%s, chapters=%s, books=%s",
            source_name,
            deleted_verses,
            deleted_chapters,
            deleted_books,
        )

    def _import_format_a(self, data: Dict[str, Any], source_name: str):
        """
        Structure:
        "Testaments": [
           {"Books": [
              {"Chapters": [
                 {"Verses": [{"ID": 1, "Text": "..."}, ...]}
              ]}
           ]}
        ]
        """
        testaments_data = data["Testaments"]

        ordered_by_testament = {
            "ancien": sorted(
                [book for book in self.mapping.values() if book.get("testament") == "ancien"],
                key=lambda x: x["order"],
            ),
            "nouveau": sorted(
                [book for book in self.mapping.values() if book.get("testament") == "nouveau"],
                key=lambda x: x["order"],
            ),
        }

        for testament_idx, testament_data in enumerate(testaments_data):
            testament_slug = "ancien" if testament_idx == 0 else "nouveau"
            ordered_books = ordered_by_testament.get(testament_slug, [])
            books_data = testament_data.get("Books", [])

            logger.info(
                "Format A mapping for testament '%s': source_books=%s, mapped_books=%s",
                testament_slug,
                len(books_data),
                len(ordered_books),
            )

            for local_idx, b_data in enumerate(books_data):
                mapped_idx = local_idx

                if mapped_idx < len(ordered_books):
                    canonical_name = ordered_books[mapped_idx]["canonical_name"]
                else:
                    canonical_name = f"Livre Inconnu {testament_slug} {mapped_idx + 1}"

                book = self.get_or_create_book(canonical_name)
                self._import_chapters(book, b_data.get("Chapters", []), source_name, ImportFormat.FORMAT_A)

    def _import_format_b(self, data: Dict[str, Any], source_name: str):
        """
        Structure:
        "books": [
            {"name": "Genesis", "chapters": [
                {"chapter": 1, "verses": [
                    {"verse": 1, "text": "..."}
                ]}
            ]}
        ]
        """
        for b_data in data.get("books", []):
            raw_name = b_data.get("name", "Unknown Book")
            book = self.get_or_create_book(raw_name)
            self._import_chapters(book, b_data.get("chapters", []), source_name, ImportFormat.FORMAT_B)

    def _import_chapters(self, book: Book, chapters_data: list, source_name: str, format_type: ImportFormat):
        """Imports chapters and verses for a specific book."""
        logger.info(f"Importing book: {book.name}")

        verses_to_create = []

        # We process chapter by chapter
        for c_idx, c_data in enumerate(chapters_data):
            # Resolve chapter number
            if format_type == ImportFormat.FORMAT_A:
                chapter_number = c_data.get("ID") or (c_idx + 1)
            else:
                chapter_number = c_data.get("chapter") or (c_idx + 1)

            chapter, _ = Chapter.objects.get_or_create(
                book=book,
                number=chapter_number,
            )

            verses_data = c_data.get("verses", []) if format_type == ImportFormat.FORMAT_B else c_data.get("Verses", [])

            # Format A: first verse often lacks ID. Keep internal counter.
            internal_number = 1

            for v_idx, v_data in enumerate(verses_data):
                if format_type == ImportFormat.FORMAT_A:
                    # In Format A, ID is often absent on first verse
                    original_id = v_data.get("ID")
                    verse_number = original_id if original_id else internal_number
                    raw_text = v_data.get("Text", "")
                    # Because JSON might reset or skip IDs, we ensure sequence increases
                    if original_id and original_id >= internal_number:
                        internal_number = original_id
                else:
                    original_id = v_data.get("verse")
                    verse_number = original_id or (v_idx + 1)
                    raw_text = v_data.get("text", "")

                internal_number += 1

                cleaned_text = CleaningService.clean_text(raw_text)

                # Instruction spec: Skip completely empty verses
                if not cleaned_text:
                    continue

                verses_to_create.append(
                    Verse(
                        chapter=chapter,
                        number=verse_number,
                        text=cleaned_text,
                        original_id=original_id,
                        original_position=v_idx,
                        source_file=source_name,
                    )
                )

        if not verses_to_create:
            logger.warning(f"No verses found for {book.name}")
            return

        # Transaction per book for atomicity and partial success capability
        try:
            with transaction.atomic():
                # Delete existing verses from this source for this book to ensure clean import
                Verse.objects.filter(chapter__book=book, source_file=source_name).delete()

                # Bulk create verses with chunk size 1000, ignore duplicates from dirty JSON files
                batch_size = 1000
                Verse.objects.bulk_create(verses_to_create, batch_size=batch_size, ignore_conflicts=True)

                # Update counters
                self._update_counters(book)

                logger.info(f"Imported {len(verses_to_create)} verses for {book.name}")

        except Exception as e:
            logger.error(f"Failed to import book {book.name}: {str(e)}")
            raise

        # Enqueue async tasks for this book
        populate_tsv_task.delay(book.id)

    def _update_counters(self, book: Book):
        """Updates verse_count on Chapter and Book models."""
        from django.db.models import Count

        chapters = list(book.chapters.annotate(vc=Count("verses")).order_by("number"))
        for chapter in chapters:
            chapter.verse_count = chapter.vc

        if chapters:
            Chapter.objects.bulk_update(chapters, ["verse_count"])

        book.verse_count = sum(c.verse_count for c in chapters)
        book.save(update_fields=["verse_count"])
