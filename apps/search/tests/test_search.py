"""Recherche transverse (lot V1-routes, B03) : visibilités et pagination par type."""


import pytest
from django.core.cache import cache
from django.db import connection
from rest_framework.test import APIClient

from apps.audio.enums import SourceKind, Visibility
from apps.audio.models import AudioSource
from apps.audio.tests.conftest import named, ready_track
from apps.bible.models import Book, Chapter, Testament, Verse
from apps.hierarchy.tests.factories import make_place, nominate, person, priest
from apps.messaging.models import MessagingAvailability
from apps.news.services import article_create, article_publish
from apps.news.tests.factories import ArticleCategoryFactory

pytestmark = pytest.mark.django_db
URL = "/api/v1/search/"


def client_for(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


@pytest.fixture(autouse=True)
def _cache():
    cache.clear()


@pytest.fixture
def world(tree):
    w = tree
    w.fidele = named(person("mt.diouf@test.sn", paroisse_suivie=w.saint_dominique), "Marie-Thérèse", "Diouf")
    w.cure = named(priest("e.tine@sd.sn"), "Emmanuel", "Tine")
    w.vicaire = named(priest("vicaire@st.sn"), "Emmanuel", "Faye")
    w.secretaire = named(person("c.coly@sd.sn"), "Cécile", "Coly")
    nominate(w.cure, "cure", w.saint_dominique)
    nominate(w.vicaire, "vicaire_paroissial", w.sainte_therese)
    nominate(w.secretaire, "secretaire_paroissial", w.saint_dominique)
    make_place(w.saint_dominique, "Chapelle Sainte-Thérèse du Point E", city="Dakar")
    category = ArticleCategoryFactory()
    published = article_create(
        author=w.secretaire, title="Kermesse de Saint-Dominique", content="Dimanche.", category=category,
        node=w.saint_dominique,
    )  # fmt: skip
    article_publish(article=published, editor=w.secretaire)
    article_create(
        author=w.secretaire, title="Kermesse secrète", content="Brouillon.", category=category, node=w.saint_dominique
    )
    source = AudioSource.objects.create(node=w.saint_dominique, kind=SourceKind.CHORALE, name="Chorale Sainte-Cécile")
    ready_track(source, "Kyrie de la messe", visibility=Visibility.PUBLIC)
    ready_track(source, "Kyrie des paroissiens", visibility=Visibility.PAROISSE)
    t = Testament.objects.create(name="Nouveau Testament", slug="nouveau", order=2)
    b = Book.objects.create(name="Jean", slug="jean", testament=t, order=43, verse_count=1)
    c = Chapter.objects.create(book=b, number=1, verse_count=1)
    Verse.objects.create(chapter=c, number=1, text="Au commencement était le Verbe.")
    with connection.cursor() as cursor:
        cursor.execute("UPDATE bible_verse SET tsv = to_tsvector('french', text);")
    return w


def test_all_types_anonymous_without_private_data(world):
    body = client_for().get(URL, {"q": "Kermesse"}).json()
    assert set(body["results"]) == {"bible", "paroisses", "lieux", "annonces", "pretres", "audio"}
    assert [a["title"] for a in body["results"]["annonces"]["items"]] == ["Kermesse de Saint-Dominique"]
    assert body["results"]["pretres"]["items"] == []  # réservé aux personnes connectées


def test_parishes_places_accent_insensitive(world):
    body = client_for().get(URL, {"q": "therese", "types": "paroisses,lieux"}).json()
    assert [p["name"] for p in body["results"]["paroisses"]["items"]] == ["Sainte-Thérèse"]
    assert [p["name"] for p in body["results"]["lieux"]["items"]] == ["Chapelle Sainte-Thérèse du Point E"]
    assert set(body["results"]) == {"paroisses", "lieux"}


def test_priests_reachable_only_names_and_offices(world):
    items = client_for(world.fidele).get(URL, {"q": "Emmanuel", "types": "pretres"}).json()["results"]["pretres"]["items"]
    assert sorted(i["name"] for i in items) == ["Emmanuel Faye", "Emmanuel Tine"]
    assert all(set(i) == {"id", "name", "office", "node_id", "node_name"} for i in items)
    MessagingAvailability.objects.create(user=world.vicaire, accepts_new_conversations=False)
    items = client_for(world.fidele).get(URL, {"q": "Emmanuel", "types": "pretres"}).json()["results"]["pretres"]["items"]
    assert [i["name"] for i in items] == ["Emmanuel Tine"]
    # La secrétaire n'est pas un prêtre joignable.
    assert client_for(world.fidele).get(URL, {"q": "Coly", "types": "pretres"}).json()["results"]["pretres"]["items"] == []


def test_audio_respects_visibility(world):
    anonymous = client_for().get(URL, {"q": "Kyrie", "types": "audio"}).json()["results"]["audio"]["items"]
    assert [t["title"] for t in anonymous] == ["Kyrie de la messe"]
    member = client_for(world.fidele).get(URL, {"q": "Kyrie", "types": "audio"}).json()["results"]["audio"]["items"]
    assert sorted(t["title"] for t in member) == ["Kyrie de la messe", "Kyrie des paroissiens"]


def test_bible_and_pagination_per_type(world):
    bible = client_for().get(URL, {"q": "commencement", "types": "bible"}).json()["results"]["bible"]
    assert bible["items"][0]["book_name"] == "Jean" and bible["next_offset"] is None
    first = bible["items"][0]
    assert first["book_id"] == Book.objects.get(name="Jean").pk
    assert first["chapter_id"] and first["chapter"] >= 1 and first["verse"] >= 1
    page = client_for(world.fidele).get(URL, {"q": "Kyrie", "types": "audio", "limit": 1}).json()["results"]["audio"]
    assert len(page["items"]) == 1 and page["next_offset"] == 1
    last = client_for(world.fidele).get(URL, {"q": "Kyrie", "types": "audio", "limit": 1, "offset": 1}).json()
    assert last["results"]["audio"]["next_offset"] is None


def test_validation(world):
    assert client_for().get(URL, {"q": "a"}).json()["error"]["code"] == "recherche_trop_courte"
    assert client_for().get(URL, {"q": "abc", "types": "dons"}).status_code == 400
