"""« Parler à un prêtre » V1 (SRS §3.7 EF-PRE-01 à 07 ; RG-09, RG-13)."""

import datetime

import pytest
from django.contrib.admin.sites import site
from django.urls import reverse
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.hierarchy.tests.factories import Tree, nominate, person, priest
from apps.messaging import services
from apps.messaging.models import MessagingAvailability
from apps.messaging.tests.factories import ConversationFactory, MessageFactory
from apps.users.models import Profile
from apps.users.tests.factories import BaseUserFactory

pytestmark = pytest.mark.django_db
SECRET = "Contenu strictement confidentiel 7f3a"


@pytest.fixture(autouse=True)
def _adults():
    """Remplace la fixture du conftest : ici, la règle de majorité s'applique réellement."""


def born(user, birth: datetime.date | None):
    Profile.objects.update_or_create(user=user, defaults={"date_of_birth": birth})
    user.refresh_from_db()
    return user


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def world(db):
    tree = Tree()
    tree.pere = priest("pere@sd.sn")
    tree.pere_non_nomme = priest("libre@sd.sn")
    tree.secretaire = person("secretaire@sd.sn")
    nominate(tree.pere, "vicaire_paroissial", tree.saint_dominique)
    nominate(tree.secretaire, "secretaire_paroissial", tree.saint_dominique)
    tree.adulte = born(person("adulte@test.sn"), datetime.date(1990, 5, 1))
    return tree


# --- Majorité (RG-13) --------------------------------------------------------------------


@freeze_time("2026-10-05")
def test_age_on_counts_birthdays():
    assert services.age_on(birth=datetime.date(2008, 10, 5), on=datetime.date(2026, 10, 5)) == 18
    assert services.age_on(birth=datetime.date(2008, 10, 6), on=datetime.date(2026, 10, 5)) == 17


@freeze_time("2026-10-05")
def test_conversation_requires_birth_date(world):
    fidele = born(person("sans@test.sn"), None)
    with pytest.raises(PermissionDeniedError) as exc:
        services.conversation_get_or_create(fidele=fidele, priest=world.pere)
    assert exc.value.code == "birth_date_required"


@freeze_time("2026-10-05")
def test_minor_cannot_open_conversation(world):
    mineur = born(person("mineur@test.sn"), datetime.date(2010, 1, 1))
    with pytest.raises(PermissionDeniedError) as exc:
        services.conversation_get_or_create(fidele=mineur, priest=world.pere)
    assert exc.value.code == "minor"


@freeze_time("2026-10-05")
def test_adult_opens_conversation_with_reachable_priest(world):
    conversation, created = services.conversation_get_or_create(fidele=world.adulte, priest=world.pere)
    assert created
    assert services.conversation_get_or_create(fidele=world.adulte, priest=world.pere) == (conversation, False)


@freeze_time("2026-10-05")
def test_api_minor_gets_403_with_explanation(world):
    mineur = born(person("mineur@test.sn"), datetime.date(2012, 1, 1))
    response = client_for(mineur).post(
        "/api/v1/messaging/conversations/create/", {"priest_user_id": str(world.pere.pk)}, format="json"
    )
    assert response.status_code == 403
    assert response.data["code"] == "minor"


# --- Joignabilité et disponibilités (EF-PRE-01, -07) --------------------------------------


@freeze_time("2026-10-05")
def test_unreachable_targets_are_refused(world):
    for target in (world.pere_non_nomme, world.secretaire, BaseUserFactory()):
        with pytest.raises(ApplicationError) as exc:
            services.conversation_get_or_create(fidele=world.adulte, priest=target)
        assert exc.value.code == "not_reachable"


@freeze_time("2026-10-05")
def test_priest_not_accepting_new_conversations(world):
    services.availability_update(user=world.pere, data={"accepts_new_conversations": False})
    with pytest.raises(ApplicationError) as exc:
        services.conversation_get_or_create(fidele=world.adulte, priest=world.pere)
    assert exc.value.code == "not_accepting"


def test_availability_reserved_to_reachable_priests(world):
    with pytest.raises(PermissionDeniedError):
        services.availability_update(user=world.secretaire, data={"note": "x"})


def test_api_availability_roundtrip(world):
    client = client_for(world.pere)
    payload = {
        "accepts_new_conversations": True,
        "absent_until": "2026-11-01",
        "reply_windows": [{"weekday": 1, "start": "18:00", "end": "20:00"}],
        "note": "Réponse sous 48 h",
    }
    assert client.put("/api/v1/messaging/availability/", payload, format="json").status_code == 200
    assert client.get("/api/v1/messaging/availability/").data["note"] == "Réponse sous 48 h"
    assert MessagingAvailability.objects.get(user=world.pere).reply_windows[0]["weekday"] == 1
    assert client_for(world.adulte).get("/api/v1/messaging/availability/").status_code == 403


def test_api_priests_lists_only_reachable(world):
    assert client_for(world.adulte).get("/api/v1/messaging/priests/").data == []  # sans paroisse suivie
    world.adulte.paroisse_suivie = world.saint_dominique
    world.adulte.save(update_fields=["paroisse_suivie"])
    response = client_for(world.adulte).get("/api/v1/messaging/priests/")
    assert response.status_code == 200
    ids = {row["user_id"] for row in response.data}
    assert str(world.pere.pk) in ids
    assert str(world.pere_non_nomme.pk) not in ids
    assert str(world.secretaire.pk) not in ids


def test_api_priests_expose_the_office_of_the_principal_assignment(world):
    """Écart F9 : office (curé, vicaire, aumônier) ; la paroisse suivie passe avant l'aumônerie."""
    from apps.hierarchy.tests.factories import make_node

    aumonerie = make_node("aumonerie", "Aumônerie des étudiants", world.dakar, code="T-AUM")
    cure = priest("cure@sd.sn")
    nominate(cure, "cure", world.saint_dominique)
    aumonier = priest("aumonier@dakar.sn")
    nominate(aumonier, "aumonier", aumonerie)
    nominate(world.pere, "aumonier", aumonerie, start_date=datetime.date(2019, 1, 1))
    world.adulte.paroisse_suivie = world.saint_dominique
    world.adulte.save(update_fields=["paroisse_suivie"])

    rows = {row["user_id"]: row for row in client_for(world.adulte).get("/api/v1/messaging/priests/").data}

    assert rows[str(cure.pk)]["office"] == {"code": "cure", "label": "Curé"}
    assert rows[str(world.pere.pk)]["office"]["code"] == "vicaire_paroissial"
    assert rows[str(aumonier.pk)]["office"]["code"] == "aumonier"


# --- Bandeau et confidentialité (EF-PRE-05, -06 ; RG-09) ------------------------------------


@freeze_time("2026-10-05")
def test_conversation_carries_confession_notice(world):
    response = client_for(world.adulte).post(
        "/api/v1/messaging/conversations/create/", {"priest_user_id": str(world.pere.pk)}, format="json"
    )
    assert response.status_code == 201
    assert response.data["confession_notice"] == services.CONFESSION_NOTICE
    assert "confession" in services.CONFESSION_NOTICE.lower()


def test_django_admin_never_shows_message_content(world, client):
    admin = BaseUserFactory(is_staff=True, is_superuser=True)
    client.force_login(admin)
    message = MessageFactory(
        conversation=ConversationFactory(participant_a=world.adulte, participant_b=world.pere), content=SECRET
    )
    checked = 0
    for model in site._registry:
        if model._meta.app_label != "messaging":
            continue
        info = (model._meta.app_label, model._meta.model_name)
        pages = [reverse("admin:%s_%s_changelist" % info)]
        instance = model.objects.first()
        if instance is not None:
            pages.append(reverse("admin:%s_%s_change" % info, args=[instance.pk]))
        for url in pages:
            response = client.get(url)
            assert response.status_code in (200, 302, 403), url
            assert SECRET not in response.content.decode(), url
            checked += 1
    assert checked >= 4
    assert message.pk
