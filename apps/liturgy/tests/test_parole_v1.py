"""La Parole V1 : jour liturgique, LITURGY_SOURCE, édition biblique, méditation (SRS §3.4)."""

import datetime

import pytest
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.bible.models import Book, Chapter, Testament, Verse
from apps.liturgy.selectors import liturgy_day
from apps.liturgy.tests.factories import AelfResourceFactory, LiturgicalDateFactory, ReadingFactory

pytestmark = pytest.mark.django_db
DAY = datetime.date(2026, 10, 4)  # 27e dimanche du temps ordinaire, année A
AELF_TEXT = "Texte AELF protégé"


@pytest.fixture
def bible():
    testament = Testament.objects.create(name="Nouveau Testament", slug="nouveau", order=2)
    book = Book.objects.create(name="Luc", slug="luc", testament=testament, order=3)
    chapter = Chapter.objects.create(book=book, number=17)
    crampon = Verse.objects.create(
        chapter=chapter, number=5, text="Augmentez en nous la foi.", source_file="crampon1923"
    )
    aelf = Verse.objects.create(chapter=chapter, number=5, text="Version AELF du verset", source_file="aelf")
    return {"crampon": crampon, "aelf": aelf}


@pytest.fixture
def day_data(bible):
    date_obj = LiturgicalDateFactory(date=DAY, zone="afrique")
    AelfResourceFactory(liturgical_date=date_obj, audio_url="https://example.org/a.mp3")
    reading = ReadingFactory(liturgical_date=date_obj, type="evangile", citation="Lc 17, 5-10", text=AELF_TEXT)
    reading.matched_verses.set([bible["crampon"], bible["aelf"]])
    return date_obj


def test_calendar_is_served_even_without_readings(settings):
    data = liturgy_day(day=DAY)
    assert data["readings_available"] is False
    assert data["calendar"]["celebration"] == "27e dimanche du temps ordinaire"
    assert (data["calendar"]["color"], data["calendar"]["sunday_cycle"]) == ("vert", "A")


def test_crampon_refs_serves_references_and_local_text_only(day_data, settings):
    settings.LITURGY_SOURCE = "crampon_refs"
    settings.BIBLE_EDITION = "crampon1923"
    data = liturgy_day(day=DAY)
    reading = data["readings"][0]
    assert reading["citation"] == "Lc 17, 5-10"
    assert reading["text"] is None
    assert [v["text"] for v in reading["verses"]] == ["Augmentez en nous la foi."]
    assert data["edition"]["code"] == "crampon1923"
    assert data["audio_url"] is None
    assert AELF_TEXT not in str(data)


def test_aelf_source_serves_aelf_text_with_notice(day_data, settings):
    settings.LITURGY_SOURCE = "aelf"
    data = liturgy_day(day=DAY)
    assert data["readings"][0]["text"] == AELF_TEXT
    assert data["readings"][0]["verses"] == []
    assert "AELF" in data["notice"]
    assert data["audio_url"] == "https://example.org/a.mp3"


def test_api_liturgy_is_public(day_data, settings):
    settings.LITURGY_SOURCE = "crampon_refs"
    client = APIClient()
    response = client.get(f"/api/v1/liturgy/{DAY.isoformat()}/")
    assert response.status_code == 200
    assert response.data["date"] == DAY.isoformat()
    with freeze_time("2026-10-04 09:00:00"):
        assert client.get("/api/v1/liturgy/today/").data["date"] == DAY.isoformat()
    assert client.get("/api/v1/liturgy/2026-02-30/").status_code == 404


def test_legacy_aelf_relay_routes_are_gone():
    client = APIClient()
    for url in ("/api/v1/liturgy/v1/messes/", "/api/v1/liturgy/v1/informations/", "/api/v1/liturgy/date/2026-10-04/"):
        assert client.get(url).status_code == 404


def test_bible_verses_follow_configured_edition(bible, settings):
    settings.BIBLE_EDITION = "crampon1923"
    chapter = bible["crampon"].chapter
    url = f"/api/v1/bible/books/{chapter.book_id}/chapters/{chapter.number}/verses/"
    texts = [v["text"] for v in APIClient().get(url, {"source": "aelf"}).data["results"]]
    assert texts == ["Augmentez en nous la foi."]  # la source demandée ne contourne pas l'édition


@freeze_time("2026-10-04 07:00:00")
def test_meditation_of_the_day_for_followed_parish(tree):
    from apps.hierarchy.tests.factories import person
    from apps.news.models import Article, ArticleCategory

    fidele = person("awa@test.sn")
    fidele.paroisse_suivie = tree.saint_dominique
    fidele.save(update_fields=["paroisse_suivie"])
    from apps.users.tests.factories import ProfileFactory

    author = person("pere@sd.sn")
    ProfileFactory(user=author, first_name="Jean", last_name="Sarr")
    Article.objects.create(
        title="Méditation : la foi comme une graine",
        excerpt="Une foi grande comme une graine de moutarde suffit.",
        content="…",
        content_type=Article.ContentType.MEDITATION,
        status=Article.Status.PUBLISHED,
        published_at=timezone.now(),
        scope_node=tree.saint_dominique,
        author=author,
        category=ArticleCategory.objects.create(name="Méditation", slug="meditation"),
    )
    meditation = liturgy_day(day=DAY, user=fidele)["meditation"]
    assert meditation["title"] == "Méditation : la foi comme une graine"
    # Extrait, auteur et date dans la même réponse : plus de second appel à /news/{id}/.
    assert meditation["excerpt"] == "Une foi grande comme une graine de moutarde suffit."
    assert meditation["author_name"] == "Jean Sarr"
    assert meditation["scope"] == "Saint-Dominique"
    assert meditation["published_at"].startswith("2026-10-04")
    assert liturgy_day(day=DAY)["meditation"] is None  # anonyme : méditations globales seulement


def test_bible_chapter_is_served_whole_in_one_request(bible, settings):
    """Écart F9 : un long chapitre (Ps 119 : 176 versets) tient en une page, plafonnée à 200."""
    settings.BIBLE_EDITION = "crampon1923"
    chapter = bible["crampon"].chapter
    Verse.objects.bulk_create(
        Verse(chapter=chapter, number=n, text=f"v{n}", source_file="crampon1923") for n in range(6, 206)
    )
    url = f"/api/v1/bible/books/{chapter.book_id}/chapters/{chapter.number}/verses/"

    whole = APIClient().get(url).data
    capped = APIClient().get(url, {"limit": 500}).data

    assert whole["count"] == 201
    assert len(whole["results"]) == 200
    assert capped["limit"] == 200
