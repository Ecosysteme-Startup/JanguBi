"""Conformité V1 : consentement, export, suppression du compte (SRS §3.9 EF-CONF-01 à 03)."""

import datetime

import pytest
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.confessions import services as confessions
from apps.confessions.models import ConfessionBooking, ConfessionSlot
from apps.core.exceptions import ApplicationError, ConflictError
from apps.documents.models import DocumentRequest
from apps.documents.tests.factories import DocumentRequestFactory
from apps.hierarchy.models import AuditEvent
from apps.hierarchy.tests.factories import Tree, make_place, nominate, person, priest
from apps.messaging.models import Conversation, Message, Notification
from apps.messaging.tests.factories import ConversationFactory, MessageFactory
from apps.users.models import Profile
from apps.users.selectors_privacy import personal_data_export
from apps.users.services_privacy import account_delete, consent_give, consent_required

pytestmark = pytest.mark.django_db
NOW = "2026-10-05 08:00:00"


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def world(db):
    tree = Tree()
    tree.pere = priest("pere@sd.sn")
    nominate(tree.pere, "vicaire_paroissial", tree.saint_dominique)
    tree.awa = person("awa@test.sn")
    Profile.objects.update_or_create(
        user=tree.awa, defaults={"first_name": "Awa", "last_name": "Diop", "date_of_birth": datetime.date(1990, 1, 1)}
    )
    tree.awa.paroisse_suivie = tree.saint_dominique
    tree.awa.save(update_fields=["paroisse_suivie"])
    return tree


# --- Consentement ---------------------------------------------------------------------


def test_consent_only_for_current_version(world, settings):
    settings.CONSENT_CURRENT_VERSION = "2026-09"
    assert consent_required(user=world.awa)
    with pytest.raises(ApplicationError):
        consent_give(user=world.awa, version="2025-01")
    consent_give(user=world.awa, version="2026-09")
    assert not consent_required(user=world.awa)
    assert AuditEvent.objects.filter(action="conformite.consentement").exists()
    settings.CONSENT_CURRENT_VERSION = "2027-01"  # nouvelle version : nouveau consentement
    assert consent_required(user=world.awa)


def test_api_consent(world, settings):
    settings.CONSENT_CURRENT_VERSION = "2026-09"
    client = client_for(world.awa)
    assert client.get("/api/v1/me/consent/").data["required"] is True
    response = client.post("/api/v1/me/consent/", {"version": "2026-09"}, format="json")
    assert response.status_code == 200 and response.data["required"] is False
    assert client.post("/api/v1/me/consent/", {"version": "old"}, format="json").status_code == 400


# --- Export ---------------------------------------------------------------------------


def test_export_contains_own_data_but_not_correspondent_messages(world):
    conversation = ConversationFactory(participant_a=world.awa, participant_b=world.pere)
    MessageFactory(conversation=conversation, sender=world.awa, content="Mon message")
    MessageFactory(conversation=conversation, sender=world.pere, content="Réponse du père")
    DocumentRequestFactory(requester=world.awa)
    data = personal_data_export(user=world.awa)
    assert data["account"]["email"] == "awa@test.sn"
    assert data["profile"]["last_name"] == "Diop"
    assert [m["content"] for m in data["conversations"][0]["my_messages"]] == ["Mon message"]
    assert "Réponse du père" not in str(data)
    assert len(data["document_requests"]) == 1


def test_api_export(world):
    response = client_for(world.awa).get("/api/v1/me/export/")
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert "attachment" in response["Content-Disposition"]
    assert APIClient().get("/api/v1/me/export/").status_code in (401, 403)


# --- Suppression ------------------------------------------------------------------------


@freeze_time(NOW)
def test_account_delete_anonymizes_and_purges(world):
    conversation = ConversationFactory(participant_a=world.awa, participant_b=world.pere)
    MessageFactory(conversation=conversation, sender=world.awa, content="secret")
    request_obj = DocumentRequestFactory(requester=world.awa, status="submitted")
    place = make_place(world.saint_dominique, "Église")
    confessions.rule_create(
        priest=world.pere, place=place, weekday=2, start_time=datetime.time(17), end_time=datetime.time(17, 30)
    )
    slot = ConfessionSlot.objects.order_by("starts_at").first()
    confessions.booking_create(slot=slot, person=world.awa)
    Notification.objects.create(user=world.awa, event_type="x", payload={})

    account_delete(user=world.awa)

    world.awa.refresh_from_db()
    assert world.awa.is_active is False
    assert world.awa.email.endswith("@deleted.invalid")
    assert world.awa.paroisse_suivie is None
    assert world.awa.profile.last_name == "" and world.awa.profile.date_of_birth is None
    assert not Conversation.objects.filter(pk=conversation.pk).exists()
    assert not Message.objects.filter(sender=world.awa).exists()
    request_obj.refresh_from_db()
    assert request_obj.status == "cancelled"
    assert request_obj.reference  # trace légale conservée
    assert request_obj.requester_last_name == "Anonymisé" and request_obj.contact_email == ""
    slot.refresh_from_db()
    assert slot.status == "libre"
    assert ConfessionBooking.objects.get().status == "annulee_fidele"
    assert not Notification.objects.filter(user=world.awa).exists()
    assert AuditEvent.objects.filter(action="conformite.suppression_compte").exists()
    assert "awa@test.sn" not in str(list(DocumentRequest.objects.values()))


def test_office_holder_cannot_delete_account(world):
    with pytest.raises(ConflictError):
        account_delete(user=world.pere)


def test_api_delete_me(world):
    client = client_for(world.awa)
    assert client.delete("/api/v1/me/").status_code == 204
    world.awa.refresh_from_db()
    assert world.awa.is_active is False
    assert client_for(world.pere).delete("/api/v1/me/").status_code == 409


def test_keycloak_account_deleted_after_commit(world, settings, monkeypatch, django_capture_on_commit_callbacks):
    from apps.authentication import tasks

    settings.KEYCLOAK_ENABLED = True
    world.awa.keycloak_sub = "kc-123"
    world.awa.save(update_fields=["keycloak_sub"])
    calls = []
    monkeypatch.setattr(tasks.keycloak_user_delete_task, "delay", lambda sub: calls.append(sub))
    with django_capture_on_commit_callbacks(execute=True):
        account_delete(user=world.awa)
    assert calls == ["kc-123"]
    world.awa.refresh_from_db()
    assert world.awa.keycloak_sub is None


def test_account_delete_erases_religious_status_and_relations(world):
    from apps.messaging.models import MessageBlock

    religieuse = person("soeur@test.sn", etat_de_vie="consacre")
    MessageBlock.objects.create(blocker=religieuse, blocked=world.pere)
    account_delete(user=religieuse)
    religieuse.refresh_from_db()
    assert (religieuse.etat_de_vie, religieuse.degre_ordre) == ("laic", "aucun")
    assert not MessageBlock.objects.filter(blocker=religieuse).exists()
