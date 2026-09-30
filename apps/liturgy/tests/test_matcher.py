import pytest

from apps.bible.models import Book, Chapter, Testament, Verse
from apps.liturgy.matcher import CitationMatcher


@pytest.fixture(autouse=True)
def reset_books_cache():
    CitationMatcher._books_cache = None
    yield
    CitationMatcher._books_cache = None


@pytest.fixture
def setup_bible_data():
    t = Testament.objects.create(name="Nouveau Testament", slug="nouveau", order=2)
    b_luc = Book.objects.create(testament=t, name="Luc", slug="luc", order=3, alt_names=["Lc"])
    b_ps = Book.objects.create(testament=t, name="Psaumes", slug="psaumes", order=19, alt_names=["Ps"])

    c_luc_6 = Chapter.objects.create(book=b_luc, number=6)
    Verse.objects.create(chapter=c_luc_6, number=36, text="Soyez miséricordieux")
    Verse.objects.create(chapter=c_luc_6, number=37, text="Ne jugez pas")
    Verse.objects.create(chapter=c_luc_6, number=38, text="Donnez et on vous donnera")

    c_ps_78 = Chapter.objects.create(book=b_ps, number=78)
    Verse.objects.create(chapter=c_ps_78, number=5, text="O Dieu les nations ont envahi")
    Verse.objects.create(chapter=c_ps_78, number=8, text="Ne te souviens plus")
    Verse.objects.create(chapter=c_ps_78, number=9, text="Secours nous")

    return {
        "luc_6": c_luc_6,
        "ps_78": c_ps_78
    }

@pytest.mark.django_db(transaction=True)
def test_matcher_standard_gospel(setup_bible_data):
    # e.g., "Lc 6, 36-38" or "Lc 6,36-38"
    verses = CitationMatcher.match("Lc 6, 36-38")
    assert len(verses) == 3
    assert verses[0].number == 36
    assert verses[2].number == 38

@pytest.mark.django_db(transaction=True)
def test_matcher_psalm_complex(setup_bible_data):
    # e.g., "Ps 78 (79), 5a.8,9" -> it should pick up book=ps, chapter=78, range 5 to 9
    verses = CitationMatcher.match("Ps 78 (79), 5a.8,9")
    assert len(verses) == 3
    assert [v.number for v in verses] == [5, 8, 9]

@pytest.mark.django_db(transaction=True)
def test_matcher_invalid_or_missing():
    verses = CitationMatcher.match("Inconnu 1, 1")
    assert verses == []
    
    verses = CitationMatcher.match("")
    assert verses == []

@pytest.mark.django_db(transaction=True)
def test_matcher_single_verse(setup_bible_data):
    verses = CitationMatcher.match("Luc 6, 37")
    assert len(verses) == 1
    assert verses[0].number == 37


@pytest.fixture
def job_9(db):
    t = Testament.objects.create(name="Ancien Testament", slug="ancien", order=1)
    job = Book.objects.create(testament=t, name="Job", slug="job", order=18, alt_names=["Jb"])
    chapter = Chapter.objects.create(book=job, number=9)
    for n in range(1, 18):
        Verse.objects.create(chapter=chapter, number=n, text=f"Job 9,{n}")
    return chapter


@pytest.mark.django_db
def test_matcher_keeps_gaps_between_ranges(job_9):
    numbers = [v.number for v in CitationMatcher.match("Jb 9, 1-12.14-16")]
    assert numbers == [*range(1, 13), 14, 15, 16]


@pytest.mark.django_db
def test_an_empty_book_list_is_not_cached(job_9):
    CitationMatcher._books_cache = []
    assert len(CitationMatcher.match("Jb 9, 1-3")) == 3


@pytest.mark.django_db
def test_readings_are_served_and_relinked_after_a_bible_reimport(job_9, client):
    import datetime

    from apps.liturgy.models import LiturgicalDate, Reading
    from apps.liturgy.selectors import liturgy_day
    from apps.liturgy.services import readings_link_verses

    day = datetime.date(2026, 9, 30)
    ld = LiturgicalDate.objects.create(date=day, zone="afrique")
    reading = Reading.objects.create(liturgical_date=ld, type="lecture_1", citation="Jb 9, 1-12.14-16", text="")
    assert reading.matched_verses.count() == 0  # Bible importée après les lectures

    served = liturgy_day(day=day)
    first = next(r for r in served["readings"] if r["citation"] == "Jb 9, 1-12.14-16")
    assert len(first["verses"]) == 15

    assert readings_link_verses() == 1
    assert reading.matched_verses.count() == 15
    assert readings_link_verses() == 0
