"""« Écrire à … » depuis une demande d'acte (lot V1-routes, G03)."""

import datetime

import pytest
from rest_framework.test import APIClient

from apps.documents.tests.factories import DocumentRequestFactory
from apps.hierarchy.models import AuditEvent
from apps.hierarchy.tests.factories import nominate, person, priest
from apps.messaging.models import Conversation
from apps.users.models import Profile

pytestmark = pytest.mark.django_db


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def world(tree):
    tree.cure = priest("cure@sd.sn")
    tree.secretaire = person("secretaire@sd.sn")
    tree.cure_st = priest("cure@st.sn")
    nominate(tree.cure, "cure", tree.saint_dominique)
    nominate(tree.secretaire, "secretaire_paroissial", tree.saint_dominique)
    nominate(tree.cure_st, "cure", tree.sainte_therese)
    tree.fidele = person("mt.diouf@test.sn")
    Profile.objects.update_or_create(user=tree.fidele, defaults={"date_of_birth": datetime.date(1980, 5, 1)})
    tree.request = DocumentRequestFactory(requester=tree.fidele, target_node=tree.saint_dominique)
    return tree


def url(world):
    return f"/api/v1/staff/documents/{world.request.pk}/conversation/"


def test_priest_opens_then_finds_the_conversation(world):
    first = client_for(world.cure).post(url(world))
    assert first.status_code == 201, first.content
    assert first.json()["created"] is True
    second = client_for(world.cure).post(url(world))
    assert second.status_code == 200 and second.json()["conversation_id"] == first.json()["conversation_id"]
    assert Conversation.objects.count() == 1
    assert AuditEvent.objects.filter(action="actes.conversation_demandeur").count() == 2


def test_secretary_is_redirected_to_phone_or_email(world):
    response = client_for(world.secretaire).post(url(world))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "messaging_not_allowed"


def test_other_parish_gets_404_and_minor_is_refused(world):
    assert client_for(world.cure_st).post(url(world)).status_code == 404
    Profile.objects.filter(user=world.fidele).update(date_of_birth=datetime.date(2012, 1, 1))
    response = client_for(world.cure).post(url(world))
    assert response.status_code == 403 and response.json()["error"]["code"] == "minor"
