"""Bible complète ou non : décide si seed_prod réimporte (l'import est atomique par livre)."""

import json

import pytest

from apps.bible.models import Book, Chapter, Testament, Verse
from apps.bible.seeders import bible_complete


def _fichier(tmp_path, *livres):
    path = tmp_path / "bible.json"
    books = [{"name": nom, "chapters": [{"chapter": 1, "verses": [{"verse": 1, "text": "…"}]}]} for nom in livres]
    path.write_text(json.dumps({"books": books}), encoding="utf-8-sig")
    return path


def _livre_importe(nom, slug, source="AELF"):
    testament, _ = Testament.objects.get_or_create(slug="ancien", defaults={"name": "Ancien Testament", "order": 1})
    book = Book.objects.create(testament=testament, name=nom, slug=slug, order=Book.objects.count() + 1)
    chapter = Chapter.objects.create(book=book, number=1)
    Verse.objects.create(chapter=chapter, number=1, text="…", source_file=source)


@pytest.mark.django_db
def test_an_interrupted_import_is_incomplete(tmp_path):
    _livre_importe("Genèse", "genese")

    assert not bible_complete(_fichier(tmp_path, "Genèse", "Exode"), "AELF")


@pytest.mark.django_db
def test_every_book_of_the_file_imported_is_complete(tmp_path):
    _livre_importe("Genèse", "genese")
    _livre_importe("Exode", "exode")

    assert bible_complete(_fichier(tmp_path, "Genèse", "Exode"), "AELF")


@pytest.mark.django_db
def test_books_of_another_source_do_not_count(tmp_path):
    _livre_importe("Genèse", "genese", source="crampon1923")

    assert not bible_complete(_fichier(tmp_path, "Genèse"), "AELF")


@pytest.mark.django_db
def test_an_unreadable_file_never_triggers_a_reimport(tmp_path):
    # Réimporter supprime d'abord tous les versets de la source (et les signets qui s'y rattachent) :
    # sans fichier lisible, on ne sait pas juger — on se contente de « une Bible est là ».
    _livre_importe("Genèse", "genese")

    assert bible_complete(tmp_path / "absent.json", "AELF")
