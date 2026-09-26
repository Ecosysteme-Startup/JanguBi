"""Déclaration d'état de vie par la personne elle-même : réponse à une demande de complément,
justificatifs téléversés via l'API fichiers, notification de la chancellerie."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.files.tests.factories import FileFactory
from apps.hierarchy.enums import StatutVerification
from apps.hierarchy.models import AuditEvent, DeclarationAttachment
from apps.hierarchy.services_offices import person_declaration_submit, person_verification_decide
from apps.hierarchy.tests.factories import nominate, person, priest
from apps.messaging.models import Notification

pytestmark = pytest.mark.django_db

ME_DECLARATION = "/api/v1/me/declaration/"
UPLOAD = "/api/v1/files/upload/standard/"


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def world(tree):
    tree.chancelier = person("chancelier@dakar.sn")
    tree.cure = priest("cure@sd.sn")
    nominate(tree.chancelier, "chancelier", tree.dakar)
    nominate(tree.cure, "cure", tree.saint_dominique)
    return tree


def _complement_requested(world):
    candidate = person("luc.bassene@example.sn", verified=False)
    person_declaration_submit(person=candidate, etat_de_vie="clerc", degre_ordre="pretre", incardination_node=world.dakar)
    person_verification_decide(actor=world.chancelier, person=candidate, decision="complement", note="Lettre manquante.")
    Notification.objects.all().delete()
    return candidate


def _body(world, **extra):
    return {"etat_de_vie": "clerc", "degre_ordre": "pretre", "incardination_node_id": str(world.dakar.pk), **extra}


def test_faithful_uploads_a_justificatif_then_declares(world):
    candidate = person("luc@example.sn", verified=False)
    client = client_for(candidate)

    upload = client.post(
        UPLOAD, {"file": SimpleUploadedFile("celebret.pdf", b"%PDF-1.4 test", content_type="application/pdf")}, format="multipart"
    )
    assert upload.status_code == 201

    response = client.post(ME_DECLARATION, _body(world, attachment_file_ids=[upload.data["id"]]), format="json")

    assert response.status_code == 200
    assert response.data["statut_verification"] == StatutVerification.DECLARE
    assert [a["file_name"] for a in response.data["attachments"]] == ["celebret.pdf"]
    assert response.data["attachments"][0]["url"]


def test_answering_a_complement_goes_back_to_declared_and_notifies_the_chancery(
    world, django_capture_on_commit_callbacks
):
    candidate = _complement_requested(world)
    lettre = FileFactory.create(uploaded_by=candidate, original_file_name="lettre.pdf")

    with django_capture_on_commit_callbacks(execute=True):
        response = client_for(candidate).post(ME_DECLARATION, _body(world, attachment_file_ids=[lettre.pk]), format="json")

    assert response.status_code == 200
    assert response.data["statut_verification"] == StatutVerification.DECLARE
    notification = Notification.objects.get(event_type="personnes.complement_fourni")
    assert notification.user == world.chancelier
    assert notification.payload == {"person_id": str(candidate.pk), "node_id": str(world.dakar.pk)}
    # Le curé (sans personnes.verifier) et la personne elle-même ne sont pas prévenus.
    assert not Notification.objects.filter(user__in=[world.cure, candidate], event_type="personnes.complement_fourni").exists()
    assert AuditEvent.objects.filter(action="personne.declaration", metadata__complement=True).exists()
    queue = client_for(world.chancelier).get("/api/v1/hierarchy/verifications/", {"statut": "declare"}).data
    assert [r["id"] for r in queue["results"]] == [str(candidate.pk)]


def test_a_first_declaration_does_not_notify_the_chancery(world, django_capture_on_commit_callbacks):
    candidate = person(verified=False)

    with django_capture_on_commit_callbacks(execute=True):
        client_for(candidate).post(ME_DECLARATION, _body(world), format="json")

    assert not Notification.objects.filter(event_type="personnes.complement_fourni").exists()


def test_justificatifs_accumulate_across_submissions(world):
    candidate = _complement_requested(world)
    first, second = FileFactory.create_batch(2, uploaded_by=candidate)
    client = client_for(candidate)

    client.post(ME_DECLARATION, _body(world, attachment_file_ids=[first.pk]), format="json")
    response = client.post(ME_DECLARATION, _body(world, attachment_file_ids=[second.pk]), format="json")

    assert {a["id"] for a in response.data["attachments"]} == {first.pk, second.pk}


def test_audio_is_not_a_justificatif(world):
    candidate = person(verified=False)
    audio = FileFactory.create(uploaded_by=candidate, original_file_name="voix.mp3", file_type="audio/mpeg")

    response = client_for(candidate).post(ME_DECLARATION, _body(world, attachment_file_ids=[audio.pk]), format="json")

    assert response.status_code == 400
    assert not DeclarationAttachment.objects.filter(person=candidate).exists()


def test_someone_elses_file_is_refused(world):
    candidate = person(verified=False)
    foreign = FileFactory.create(uploaded_by=person())

    response = client_for(candidate).post(ME_DECLARATION, _body(world, attachment_file_ids=[foreign.pk]), format="json")

    assert response.status_code == 403


def test_more_than_five_justificatifs_is_refused(world):
    candidate = person(verified=False)
    client = client_for(candidate)
    client.post(
        ME_DECLARATION,
        _body(world, attachment_file_ids=[f.pk for f in FileFactory.create_batch(4, uploaded_by=candidate)]),
        format="json",
    )

    response = client.post(
        ME_DECLARATION,
        _body(world, attachment_file_ids=[f.pk for f in FileFactory.create_batch(2, uploaded_by=candidate)]),
        format="json",
    )

    assert response.status_code == 400


def test_a_cleric_must_give_an_order_degree(world):
    response = client_for(person(verified=False)).post(ME_DECLARATION, _body(world, degre_ordre="aucun"), format="json")
    assert response.status_code == 400


def test_incardination_must_be_a_diocese_or_institute(world):
    response = client_for(person(verified=False)).post(
        ME_DECLARATION, _body(world, incardination_node_id=str(world.saint_dominique.pk)), format="json"
    )
    assert response.status_code == 400


def test_declaration_requires_authentication(world):
    assert APIClient().post(ME_DECLARATION, _body(world), format="json").status_code in (401, 403)
    assert APIClient().get(ME_DECLARATION).status_code in (401, 403)
