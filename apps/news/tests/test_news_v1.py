"""Annonces V1 : capacités, programmation, dimanche, lectures, flux (SRS §3.5)."""

import datetime

import pytest
from django.core import mail
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.hierarchy.tests.factories import make_place, nominate, person, priest
from apps.messaging.models import Notification
from apps.news.models import Article, ArticleRead
from apps.news.selectors import article_list_published, feed_for
from apps.news.services import (
    article_create,
    article_delete,
    article_mark_read,
    article_publish,
    article_unpublish,
    article_update,
    articles_publish_due,
)
from apps.news.tests.factories import ArticleCategoryFactory
from apps.users.tests.factories import SuperAdminFactory

pytestmark = pytest.mark.django_db
SUNDAY = datetime.date(2026, 9, 27)


@pytest.fixture
def world(tree):
    tree.category = ArticleCategoryFactory()
    tree.secretaire = person("secretaire@sd.sn")
    tree.cure_thies = priest("cure@thies.sn")
    nominate(tree.secretaire, "secretaire_paroissial", tree.saint_dominique)
    nominate(tree.cure_thies, "cure", tree.thies_parish)
    return tree


def draft(world, **kwargs):
    fields = {
        "author": world.secretaire,
        "title": "Kermesse paroissiale",
        "content": "Dimanche après la messe.",
        "category": world.category,
        "node": world.saint_dominique,
    }
    return article_create(**{**fields, **kwargs})


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# --- Autorisation (EF-PAROI-01) -----------------------------------------------------------------


def test_secretary_publishes_in_her_parish(world):
    article = article_publish(article=draft(world), editor=world.secretaire)
    assert article.status == Article.Status.PUBLISHED and article.scope_node == world.saint_dominique


def test_secretary_cannot_publish_in_another_parish(world):
    with pytest.raises(PermissionDeniedError):
        draft(world, node=world.sainte_therese)


def test_global_content_is_for_the_platform_only(world):
    with pytest.raises(PermissionDeniedError):
        draft(world, node=None)
    article = draft(world, node=None, author=SuperAdminFactory.create())
    assert article.scope_node is None


def test_pastoral_letter_is_frozen(world):
    with pytest.raises(ApplicationError) as exc:
        draft(world, content_type=Article.ContentType.PASTORAL_LETTER)
    assert exc.value.code == "content_type_frozen"


def test_place_must_belong_to_the_node(world):
    other_place = make_place(world.sainte_therese, "Église Sainte-Thérèse")
    with pytest.raises(ApplicationError):
        draft(world, place=other_place)
    own = make_place(world.saint_dominique, "Chapelle UCAD")
    assert draft(world, place=own).scope_place == own


def test_html_is_sanitized(world):
    article = draft(world, content="<p>Bonjour</p><script>alert(1)</script>", content_format="html")
    assert "<script>" not in article.content and "<p>Bonjour</p>" in article.content


# --- Dimanche (EF-PAROI-02) -----------------------------------------------------------------------


def test_sunday_notice_needs_a_sunday(world):
    with pytest.raises(ApplicationError):
        draft(world, is_sunday_notice=True)
    with pytest.raises(ApplicationError):
        draft(world, is_sunday_notice=True, sunday_date=SUNDAY + datetime.timedelta(days=1))


def test_sunday_filter(world):
    sunday = article_publish(article=draft(world, is_sunday_notice=True, sunday_date=SUNDAY), editor=world.secretaire)
    article_publish(article=draft(world, title="Autre"), editor=world.secretaire)

    assert list(article_list_published(sunday=SUNDAY)) == [sunday]


# --- Programmation (EF-PAROI-03) -----------------------------------------------------------------


def test_scheduled_publication_then_task(world):
    later = timezone.now() + datetime.timedelta(hours=2)
    article = article_publish(article=draft(world), editor=world.secretaire, publish_at=later)
    assert article.status == Article.Status.SCHEDULED
    assert articles_publish_due() == 0

    with freeze_time(later + datetime.timedelta(minutes=1)):
        assert articles_publish_due() == 1
    article.refresh_from_db()
    assert article.status == Article.Status.PUBLISHED and article.published_at == later


def test_unpublish_then_delete(world):
    article = article_publish(article=draft(world), editor=world.secretaire)
    with pytest.raises(ApplicationError):
        article_delete(article=article, editor=world.secretaire)
    article_unpublish(article=article, editor=world.secretaire, reason="Erreur de date")
    article_delete(article=article, editor=world.secretaire)
    assert not Article.objects.filter(pk=article.pk).exists()


def test_update_keeps_authorization(world):
    article = draft(world)
    with pytest.raises(PermissionDeniedError):
        article_update(article=article, editor=world.cure_thies, data={"title": "Piraté"})
    assert (
        article_update(article=article, editor=world.secretaire, data={"title": "Kermesse 2026"}).title
        == "Kermesse 2026"
    )


# --- Lectures (EF-PAROI-05) -------------------------------------------------------------------


def test_one_read_per_person(world):
    article = article_publish(article=draft(world), editor=world.secretaire)
    reader = person()
    assert article_mark_read(article=article, user=reader) is True
    assert article_mark_read(article=article, user=reader) is False
    assert ArticleRead.objects.filter(article=article).count() == 1


# --- Flux (EF-PAROI-04) -----------------------------------------------------------------------


def test_feed_shows_global_followed_parish_and_its_diocese(world):
    fidele = person(paroisse_suivie=world.saint_dominique)
    admin = SuperAdminFactory.create()
    global_ = article_publish(article=draft(world, node=None, author=admin), editor=admin)
    parish = article_publish(article=draft(world), editor=world.secretaire)
    eveque = person(ordre="eveque")
    nominate(eveque, "eveque_diocesain", world.dakar)
    diocese = article_publish(article=draft(world, node=world.dakar, author=eveque), editor=eveque)
    other = article_publish(
        article=draft(world, node=world.thies_parish, author=world.cure_thies), editor=world.cure_thies
    )

    feed = set(feed_for(user=fidele))

    assert {global_, parish, diocese} <= feed
    assert other not in feed


def test_feed_without_followed_parish_is_global_only(world):
    admin = SuperAdminFactory.create()
    global_ = article_publish(article=draft(world, node=None, author=admin), editor=admin)
    article_publish(article=draft(world), editor=world.secretaire)
    assert list(feed_for(user=person())) == [global_]


# --- Notifications (EF-PAROI-08) ----------------------------------------------------------------


def test_publication_notifies_followers_in_app_and_by_email(world, django_capture_on_commit_callbacks):
    follower = person("fidele@sd.sn", paroisse_suivie=world.saint_dominique)
    person("autre@st.sn", paroisse_suivie=world.sainte_therese)

    with freeze_time("2026-09-25 10:00:00"), django_capture_on_commit_callbacks(execute=True):
        article_publish(article=draft(world), editor=world.secretaire)

    notes = Notification.objects.filter(event_type="news.published")
    assert list(notes.values_list("user_id", flat=True)) == [follower.pk]
    assert [m.to for m in mail.outbox] == [["fidele@sd.sn"]]
    assert "Kermesse" in mail.outbox[0].subject


# --- API ------------------------------------------------------------------------------------


def test_public_list_hides_drafts_and_read_counts(world):
    published = article_publish(article=draft(world), editor=world.secretaire)
    draft(world, title="Brouillon")

    response = APIClient().get("/api/v1/news/", {"node": str(world.doyenne.pk)})

    assert response.status_code == 200
    assert [a["id"] for a in response.data["results"]] == [str(published.pk)]
    assert "reads_count" not in response.data["results"][0]


def test_staff_flow_over_http(world):
    client = client_for(world.secretaire)
    created = client.post(
        "/api/v1/staff/news/",
        {
            "node_id": str(world.saint_dominique.pk),
            "title": "Messe des familles",
            "content": "…",
            "category_id": world.category.pk,
        },
        format="json",
    )
    article_id = created.data["id"]
    published = client.post(f"/api/v1/staff/news/{article_id}/publish/", {}, format="json")
    client_for(person()).post(f"/api/v1/news/{article_id}/read/")
    listing = client.get("/api/v1/staff/news/")

    assert created.status_code == 201 and created.data["status"] == "draft"
    assert published.data["status"] == "published"
    assert listing.data["results"][0]["reads_count"] == 1


def test_staff_cannot_reach_other_parish_articles(world):
    article = draft(world)
    response = client_for(world.cure_thies).get(f"/api/v1/staff/news/{article.pk}/")
    assert response.status_code == 404


def test_fidele_has_no_staff_access(world):
    assert client_for(person()).get("/api/v1/staff/news/").status_code == 403


def test_me_feed_api(world):
    article_publish(article=draft(world), editor=world.secretaire)
    fidele = person(paroisse_suivie=world.saint_dominique)
    response = client_for(fidele).get("/api/v1/me/feed/")
    assert response.status_code == 200 and response.data["count"] == 1


def test_reactions_api(world):
    article = article_publish(article=draft(world), editor=world.secretaire)
    client = client_for(person())
    response = client.put(
        f"/api/v1/news/{article.pk}/reactions/", {"reaction_type": "pray", "active": True}, format="json"
    )
    assert response.data["reactions"] == {"counts": {"pray": 1, "amen": 0, "attend": 0}, "mine": ["pray"]}


def test_public_detail_of_a_draft_is_404(world):
    assert APIClient().get(f"/api/v1/news/{draft(world).pk}/").status_code == 404


def test_scheduled_article_cannot_be_deleted(world):
    later = timezone.now() + datetime.timedelta(hours=2)
    article = article_publish(article=draft(world), editor=world.secretaire, publish_at=later)
    with pytest.raises(ApplicationError):
        article_delete(article=article, editor=world.secretaire)


def test_one_failing_scheduled_article_does_not_block_the_others(world, monkeypatch):
    from apps.news import services

    later = timezone.now() + datetime.timedelta(minutes=5)
    first = article_publish(article=draft(world, title="A"), editor=world.secretaire, publish_at=later)
    second = article_publish(article=draft(world, title="B"), editor=world.secretaire, publish_at=later)
    real = services._publish_now

    def flaky(*, article, at):
        if article.pk == first.pk:
            raise RuntimeError("panne simulée")
        real(article=article, at=at)

    monkeypatch.setattr(services, "_publish_now", flaky)
    with freeze_time(later + datetime.timedelta(minutes=1)):
        assert articles_publish_due() == 1
    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.status, second.status) == (Article.Status.SCHEDULED, Article.Status.PUBLISHED)


def test_priest_publishes_a_meditation_of_the_day(world):
    """EF-PAR-05 : la méditation est un type d'article publiable par annonces.publier."""
    from apps.news.services import article_create

    article = article_create(
        author=world.secretaire,
        title="Méditation du jour",
        content="…",
        category=world.category,
        node=world.saint_dominique,
        content_type=Article.ContentType.MEDITATION,
    )
    assert article.content_type == "meditation"
