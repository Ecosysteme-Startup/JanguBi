"""Annonces : filtres staff, bannière, option de notification, lieu en modification,
feuille d'annonces du dimanche (écarts F9, lot g4)."""

import datetime

import pytest
from django.core import mail
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.emails.models import Email
from apps.files.tests.factories import FileFactory, PendingFileFactory
from apps.hierarchy.tests.factories import make_place, nominate, person, priest
from apps.messaging.models import Notification, NotificationPreference
from apps.news.models import Article
from apps.news.services import article_create, article_publish, article_update, articles_publish_due
from apps.news.tests.factories import ArticleCategoryFactory, ArticleFactory

pytestmark = pytest.mark.django_db
SUNDAY = datetime.date(2026, 9, 27)


@pytest.fixture
def world(tree):
    tree.category = ArticleCategoryFactory()
    tree.secretaire = person("secretaire@sd.sn")
    tree.cure_thies = priest("cure@thies.sn")
    nominate(tree.secretaire, "secretaire_paroissial", tree.saint_dominique)
    nominate(tree.cure_thies, "cure", tree.thies_parish)
    tree.eglise = make_place(tree.saint_dominique, "Église Saint-Dominique")
    tree.chapelle = make_place(tree.saint_dominique, "Chapelle de la Cité U")
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


def image(owner, **kwargs):
    return FileFactory(uploaded_by=owner, file="covers/parvis.jpg", file_type="image/jpeg", **kwargs)


# --- Filtres staff : q et lieu -----------------------------------------------------------------


def test_staff_filters_by_text_and_place(world):
    at_chapel = draft(world, title="Messe de la Cité U", place=world.chapelle)
    draft(world, title="Chorale", content="Répétition samedi à la chapelle.", place=world.eglise)
    draft(world, title="Denier du culte")
    client = client_for(world.secretaire)

    by_place = client.get("/api/v1/staff/news/", {"place": world.chapelle.pk})
    by_text = client.get("/api/v1/staff/news/", {"q": "chapelle"})
    by_both = client.get("/api/v1/staff/news/", {"q": "cité", "place": world.chapelle.pk})

    assert [a["id"] for a in by_place.data["results"]] == [str(at_chapel.pk)]
    assert [a["title"] for a in by_text.data["results"]] == ["Chorale"]
    assert [a["id"] for a in by_both.data["results"]] == [str(at_chapel.pk)]


def test_text_filter_is_bounded(world):
    response = client_for(world.secretaire).get("/api/v1/staff/news/", {"q": "x" * 101})
    assert response.status_code == 400


# --- Bannière -----------------------------------------------------------------------------------


def test_cover_image_is_attached_and_exposed(world):
    cover = image(world.secretaire)
    client = client_for(world.secretaire)

    created = client.post(
        "/api/v1/staff/news/",
        {
            "node_id": str(world.saint_dominique.pk),
            "title": "Quête impérée",
            "content": "…",
            "category_id": world.category.pk,
            "cover_image_id": cover.pk,
            "cover_image_alt": "Le parvis de l'église un dimanche matin",
        },
        format="json",
    )
    article_publish(article=Article.objects.get(pk=created.data["id"]), editor=world.secretaire)
    public = APIClient().get(f"/api/v1/news/{created.data['id']}/")

    assert created.status_code == 201
    assert created.data["cover_image_id"] == cover.pk and "parvis" in created.data["cover_image_url"]
    assert public.data["cover_image_url"].split("?")[0] == created.data["cover_image_url"].split("?")[0]
    assert created.data["cover_image_alt"] == public.data["cover_image_alt"] == "Le parvis de l'église un dimanche matin"
    assert public.data["cover_image_decorative"] is False


def test_cover_must_be_a_finished_image_of_mine(world):
    with pytest.raises(ApplicationError) as not_image:
        draft(world, cover_image_id=FileFactory(uploaded_by=world.secretaire).pk)  # un PDF
    with pytest.raises(ApplicationError) as pending:
        draft(world, cover_image_id=PendingFileFactory(uploaded_by=world.secretaire).pk)
    with pytest.raises(PermissionDeniedError):
        draft(world, cover_image_id=image(person()).pk)
    with pytest.raises(ApplicationError) as missing:
        draft(world, cover_image_id=999_999)

    assert not_image.value.code == "cover_not_image"
    assert pending.value.code == "file_incomplete"
    assert missing.value.code == "file_not_found"


def test_cover_can_be_replaced_kept_or_removed(world):
    article = draft(world, cover_image_id=image(world.secretaire).pk, cover_image_alt="Le parvis")
    cure = person("cure@sd.sn")
    nominate(cure, "cure", world.saint_dominique)

    # Un collègue renvoie la bannière existante telle quelle : pas de refus.
    kept = article_update(article=article, editor=cure, data={"cover_image_id": article.cover_image_id, "title": "T"})
    replaced = article_update(article=kept, editor=cure, data={"cover_image_id": image(cure).pk})
    alt_after_replace = replaced.cover_image_alt
    removed = article_update(article=replaced, editor=cure, data={"cover_image_id": None})

    assert kept.title == "T"
    assert alt_after_replace == "Le parvis"
    assert removed.cover_image is None
    assert removed.cover_image_alt == ""


# --- Texte alternatif de la bannière ----------------------------------------------------------------


def test_cover_without_alt_is_refused_unless_decorative(world):
    with pytest.raises(ApplicationError) as missing:
        draft(world, cover_image_id=image(world.secretaire).pk)
    with pytest.raises(ApplicationError) as blank:
        draft(world, cover_image_id=image(world.secretaire).pk, cover_image_alt="   ")
    decorative = draft(
        world, cover_image_id=image(world.secretaire).pk, cover_image_alt="ignoré", cover_image_decorative=True
    )

    assert missing.value.code == blank.value.code == "cover_alt_required"
    assert decorative.cover_image_decorative is True
    assert decorative.cover_image_alt == ""


def test_alt_is_ignored_without_cover(world):
    article = draft(world, cover_image_alt="Rien à décrire", cover_image_decorative=True)

    assert article.cover_image_alt == ""
    assert article.cover_image_decorative is False


def test_update_checks_final_cover_alt_state(world):
    article = draft(world, cover_image_id=image(world.secretaire).pk, cover_image_alt="  Le parvis  ")

    with pytest.raises(ApplicationError) as cleared:
        article_update(article=article, editor=world.secretaire, data={"cover_image_alt": ""})
    article.refresh_from_db()
    decorative = article_update(article=article, editor=world.secretaire, data={"cover_image_decorative": True})
    alt_when_decorative = decorative.cover_image_alt
    described = article_update(
        article=decorative,
        editor=world.secretaire,
        data={"cover_image_decorative": False, "cover_image_alt": "La chorale"},
    )

    assert cleared.value.code == "cover_alt_required"
    assert alt_when_decorative == ""
    assert described.cover_image_alt == "La chorale" and described.cover_image_decorative is False


def test_api_refuses_cover_without_alt(world):
    response = client_for(world.secretaire).post(
        "/api/v1/staff/news/",
        {
            "node_id": str(world.saint_dominique.pk),
            "title": "Quête",
            "content": "…",
            "category_id": world.category.pk,
            "cover_image_id": image(world.secretaire).pk,
        },
        format="json",
    )

    assert response.status_code == 400
    assert Article.objects.count() == 0


def test_public_list_exposes_cover_alt(world):
    article = draft(world, cover_image_id=image(world.secretaire).pk, cover_image_alt="Le parvis")
    article_publish(article=article, editor=world.secretaire)

    listed = APIClient().get("/api/v1/news/", {"node": str(world.saint_dominique.pk)})

    [item] = listed.data["results"]
    assert item["cover_image_alt"] == "Le parvis" and item["cover_image_decorative"] is False


# --- Lieu modifiable ------------------------------------------------------------------------------


def test_place_can_be_changed_and_cleared_in_patch(world):
    article = draft(world, place=world.eglise)
    client = client_for(world.secretaire)

    moved = client.patch(f"/api/v1/staff/news/{article.pk}/", {"place_id": world.chapelle.pk}, format="json")
    cleared = client.patch(f"/api/v1/staff/news/{article.pk}/", {"place_id": None}, format="json")

    assert moved.status_code == 200 and moved.data["scope"]["place_id"] == world.chapelle.pk
    assert cleared.data["scope"]["place_id"] is None


def test_place_of_another_node_is_refused_in_patch(world):
    article = draft(world)
    elsewhere = make_place(world.sainte_therese, "Église Sainte-Thérèse")

    response = client_for(world.secretaire).patch(
        f"/api/v1/staff/news/{article.pk}/", {"place_id": elsewhere.pk}, format="json"
    )

    assert response.status_code == 400 and response.data["error"]["code"] == "place_not_in_node"


# --- Option « notifier les fidèles » --------------------------------------------------------------


def test_publication_without_notification(world, django_capture_on_commit_callbacks):
    person("fidele@sd.sn", paroisse_suivie=world.saint_dominique)
    article = draft(world)

    with django_capture_on_commit_callbacks(execute=True):
        response = client_for(world.secretaire).post(
            f"/api/v1/staff/news/{article.pk}/publish/", {"notify": False}, format="json"
        )

    assert response.status_code == 200 and response.data["notify_followers"] is False
    assert not Notification.objects.filter(event_type="news.published").exists()
    assert mail.outbox == []


def test_scheduled_publication_keeps_the_notification_choice(world, django_capture_on_commit_callbacks):
    person("fidele@sd.sn", paroisse_suivie=world.saint_dominique)
    with freeze_time("2026-09-24 10:00:00"):
        article_publish(
            article=draft(world),
            editor=world.secretaire,
            publish_at=datetime.datetime(2026, 9, 26, 12, tzinfo=datetime.UTC),
            notify=False,
        )
    with freeze_time("2026-09-26 12:05:00"), django_capture_on_commit_callbacks(execute=True):
        assert articles_publish_due() == 1

    assert not Notification.objects.filter(event_type="news.published").exists()


def test_notification_respects_topic_preference_and_quiet_hours(world, django_capture_on_commit_callbacks):
    muted = person("muet@sd.sn", paroisse_suivie=world.saint_dominique)
    night = person("nuit@sd.sn", paroisse_suivie=world.saint_dominique)
    NotificationPreference.objects.create(user=muted, topic_annonces=False)
    NotificationPreference.objects.create(user=night)  # silence 22 h → 6 h par défaut

    with freeze_time("2026-09-25 23:00:00"), django_capture_on_commit_callbacks(execute=True):
        article_publish(article=draft(world, notify_followers=True), editor=world.secretaire, notify=True)

    assert list(Notification.objects.filter(event_type="news.published").values_list("user_id", flat=True)) == [
        night.pk
    ]
    # Le sujet coupé exclut aussi l'e-mail ; la plage de silence est calculée par le
    # système de notifications commun (testé dans apps/messaging et apps/agenda).
    assert list(Email.objects.values_list("to", flat=True)) == ["nuit@sd.sn"]


# --- Feuille d'annonces du dimanche ---------------------------------------------------------------


def test_sunday_sheet_lists_parish_then_diocese_notices(world):
    parish = article_publish(
        article=draft(world, title="Quête impérée", is_sunday_notice=True, sunday_date=SUNDAY), editor=world.secretaire
    )
    with freeze_time("2026-09-24 10:00:00"):
        scheduled = article_publish(
            article=draft(world, title="Chorale", is_sunday_notice=True, sunday_date=SUNDAY, place=world.eglise),
            editor=world.secretaire,
            publish_at=datetime.datetime(2026, 9, 26, 12, tzinfo=datetime.UTC),
        )
    diocese = ArticleFactory(
        title="Lettre de l'archevêque",
        author=world.secretaire,
        scope_node=world.dakar,
        status="published",
        is_sunday_notice=True,
        sunday_date=SUNDAY,
    )
    draft(world, title="Brouillon", is_sunday_notice=True, sunday_date=SUNDAY)
    draft(world, title="Autre dimanche", is_sunday_notice=True, sunday_date=SUNDAY + datetime.timedelta(days=7))
    ArticleFactory(
        author=world.secretaire, scope_node=world.dakar, status="draft", is_sunday_notice=True, sunday_date=SUNDAY
    )

    response = client_for(world.secretaire).get(
        "/api/v1/staff/news/sunday-sheet/", {"node": str(world.saint_dominique.pk), "date": SUNDAY.isoformat()}
    )

    assert response.status_code == 200
    assert response.data["node_name"] == "Saint-Dominique" and response.data["sunday"] == SUNDAY.isoformat()
    ids = [item["id"] for item in response.data["items"]]
    assert set(ids[:2]) == {str(parish.pk), str(scheduled.pk)} and ids[2] == str(diocese.pk)
    assert len(ids) == 3
    assert response.data["items"][2]["scope"]["node_name"] == "Archidiocèse de Dakar"


def test_sunday_sheet_defaults_to_the_coming_sunday(world):
    article_publish(article=draft(world, is_sunday_notice=True, sunday_date=SUNDAY), editor=world.secretaire)
    with freeze_time("2026-09-24 10:00:00"):
        response = client_for(world.secretaire).get(
            "/api/v1/staff/news/sunday-sheet/", {"node": str(world.saint_dominique.pk)}
        )
    assert response.data["sunday"] == SUNDAY.isoformat() and len(response.data["items"]) == 1


def test_sunday_sheet_validation_and_scope(world):
    client = client_for(world.secretaire)
    not_sunday = client.get(
        "/api/v1/staff/news/sunday-sheet/", {"node": str(world.saint_dominique.pk), "date": "2026-09-26"}
    )
    other_parish = client.get("/api/v1/staff/news/sunday-sheet/", {"node": str(world.sainte_therese.pk)})
    missing_node = client.get("/api/v1/staff/news/sunday-sheet/")

    assert not_sunday.status_code == 400
    assert other_parish.status_code == 403
    assert missing_node.status_code == 400


def test_sunday_sheet_requires_authentication_and_capability(world):
    params = {"node": str(world.saint_dominique.pk)}
    assert APIClient().get("/api/v1/staff/news/sunday-sheet/", params).status_code == 401
    assert client_for(person()).get("/api/v1/staff/news/sunday-sheet/", params).status_code == 403
