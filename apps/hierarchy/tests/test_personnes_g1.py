"""Recherche de personne à nommer, équipe en lecture, vérifications enrichies et complément demandé."""

import pytest
from rest_framework.test import APIClient

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.emails.models import Email
from apps.files.tests.factories import FileFactory, PendingFileFactory
from apps.hierarchy.enums import StatutVerification
from apps.hierarchy.models import AuditEvent, DeclarationAttachment
from apps.hierarchy.persons import email_mask
from apps.hierarchy.services_offices import person_declaration_submit, person_verification_decide
from apps.hierarchy.tests.factories import nominate, person, priest
from apps.messaging.models import Notification
from apps.users.tests.factories import ProfileFactory

pytestmark = pytest.mark.django_db

PERSONS = "/api/v1/hierarchy/persons/"
ASSIGNMENTS = "/api/v1/hierarchy/assignments/"
VERIFICATIONS = "/api/v1/hierarchy/verifications/"


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def world(tree):
    tree.chancelier = person("chancelier@dakar.sn")
    tree.cure = priest("cure@sd.sn")
    tree.secretaire = person("secretaire@sd.sn")
    nominate(tree.chancelier, "chancelier", tree.dakar)
    nominate(tree.cure, "cure", tree.saint_dominique)
    nominate(tree.secretaire, "secretaire_paroissial", tree.saint_dominique)
    return tree


def _named(email: str, first: str, last: str, **kwargs):
    user = person(email, **kwargs)
    ProfileFactory.create(user=user, first_name=first, last_name=last)
    return user


# --- 1. Recherche de personne ----------------------------------------------------------------


def test_email_mask():
    assert email_mask("augustin.ndiaye@gmail.com") == "a•••e@gmail.com"
    assert email_mask("ab@x.sn") == "a•••@x.sn"
    assert email_mask("") == "•••"


def test_person_search_by_name_returns_only_what_is_needed(world):
    target = _named("germaine.faye@example.sn", "Germaine", "Faye")
    _named("autre@example.sn", "Joseph", "Mendy")

    response = client_for(world.cure).get(PERSONS, {"q": "faye"})

    assert response.status_code == 200
    assert response.data["count"] == 1
    row = response.data["results"][0]
    assert row["id"] == str(target.pk)
    assert row["full_name"] == "Germaine Faye"
    assert row["email_masked"] == "g•••e@example.sn"
    assert set(row) == {
        "id",
        "full_name",
        "email_masked",
        "etat_de_vie",
        "degre_ordre",
        "statut_verification",
        "incardination_node",
    }


def test_person_search_matches_every_word_and_email(world):
    _named("g.faye@example.sn", "Germaine", "Faye")
    _named("g.sarr@example.sn", "Germaine", "Sarr")
    client = client_for(world.cure)

    assert client.get(PERSONS, {"q": "germaine sarr"}).data["count"] == 1
    assert client.get(PERSONS, {"q": "g.faye@"}).data["count"] == 1


def test_person_search_skips_inactive_accounts(world):
    _named("parti@example.sn", "Parti", "Ailleurs", is_active=False)
    assert client_for(world.cure).get(PERSONS, {"q": "ailleurs"}).data["count"] == 0


def test_person_search_needs_two_characters(world):
    response = client_for(world.cure).get(PERSONS, {"q": "a"})
    assert response.status_code == 400
    assert client_for(world.cure).get(PERSONS).status_code == 400


def test_person_search_is_paginated(world):
    for i in range(12):
        _named(f"ndiaye{i}@example.sn", "Jean", f"Ndiaye{i:02d}")
    response = client_for(world.cure).get(PERSONS, {"q": "ndiaye", "limit": 5})
    assert response.data["count"] == 12
    assert len(response.data["results"]) == 5


def test_person_search_is_forbidden_without_offices_nommer(world):
    _named("germaine.faye@example.sn", "Germaine", "Faye")
    # Secrétaire : tableau_bord.voir mais pas offices.nommer ; fidèle : aucune capacité.
    assert client_for(world.secretaire).get(PERSONS, {"q": "faye"}).status_code == 403
    assert client_for(person()).get(PERSONS, {"q": "faye"}).status_code == 403


def test_person_search_requires_authentication(world):
    assert APIClient().get(PERSONS, {"q": "faye"}).status_code in (401, 403)


# --- 2. Équipe en lecture ---------------------------------------------------------------


def test_team_is_readable_with_tableau_bord_voir(world):
    catechiste = person()
    nominate(catechiste, "catechiste", world.saint_dominique)

    response = client_for(world.secretaire).get(ASSIGNMENTS, {"node": str(world.saint_dominique.pk)})

    assert response.status_code == 200
    holders = {row["person"]["id"] for row in response.data["results"]}
    assert {str(world.cure.pk), str(world.secretaire.pk), str(catechiste.pk)} <= holders


def test_team_reading_is_scoped_to_the_node(world):
    other = priest()
    nominate(other, "cure", world.sainte_therese)

    response = client_for(world.secretaire).get(ASSIGNMENTS, {"node": str(world.doyenne.pk)})

    holders = {row["person"]["id"] for row in response.data["results"]}
    assert str(other.pk) not in holders


def test_team_detail_is_readable_but_not_writable_with_tableau_bord_voir(world):
    catechiste = person()
    assignment = nominate(catechiste, "catechiste", world.saint_dominique)
    client = client_for(world.secretaire)

    assert client.get(f"{ASSIGNMENTS}{assignment.pk}/").status_code == 200
    assert client.patch(f"{ASSIGNMENTS}{assignment.pk}/", {"action": "terminer"}, format="json").status_code == 403


def test_team_is_invisible_to_a_plain_faithful(world):
    response = client_for(person()).get(ASSIGNMENTS, {"node": str(world.saint_dominique.pk)})
    assert response.status_code == 200
    assert response.data["count"] == 0


# --- 3. Vérifications enrichies et complément ---------------------------------------------


def _declare(world, **kwargs):
    candidate = _named("luc.bassene@example.sn", "Luc", "Bassène", verified=False)
    person_declaration_submit(
        person=candidate, etat_de_vie="clerc", degre_ordre="pretre", incardination_node=world.dakar, **kwargs
    )
    return candidate


def test_declaration_attaches_own_finished_files(world):
    candidate = _named("luc@example.sn", "Luc", "Bassène", verified=False)
    celebret = FileFactory.create(uploaded_by=candidate, original_file_name="celebret-2026.pdf")

    person_declaration_submit(
        person=candidate,
        etat_de_vie="clerc",
        degre_ordre="pretre",
        incardination_node=world.dakar,
        attachment_file_ids=[celebret.pk],
    )

    candidate.refresh_from_db()
    assert candidate.declared_at is not None
    assert list(DeclarationAttachment.objects.filter(person=candidate).values_list("file_id", flat=True)) == [
        celebret.pk
    ]


@pytest.mark.parametrize(
    ("factory", "owner_is_candidate", "error"),
    [(FileFactory, False, PermissionDeniedError), (PendingFileFactory, True, ApplicationError)],
)
def test_declaration_refuses_foreign_or_unfinished_files(world, factory, owner_is_candidate, error):
    candidate = person(verified=False)
    file_obj = factory.create(uploaded_by=candidate if owner_is_candidate else person())
    with pytest.raises(error):
        person_declaration_submit(
            person=candidate, etat_de_vie="clerc", degre_ordre="pretre", attachment_file_ids=[file_obj.pk]
        )


def test_verification_list_is_enriched(world):
    candidate = _named("luc@example.sn", "Luc", "Bassène", verified=False)
    celebret = FileFactory.create(uploaded_by=candidate, original_file_name="celebret-2026.pdf")
    person_declaration_submit(
        person=candidate,
        etat_de_vie="clerc",
        degre_ordre="pretre",
        incardination_node=world.dakar,
        attachment_file_ids=[celebret.pk],
    )

    row = client_for(world.chancelier).get(VERIFICATIONS).data["results"][0]

    assert row["full_name"] == "Luc Bassène"
    assert row["declared_at"] is not None
    assert [a["file_name"] for a in row["attachments"]] == ["celebret-2026.pdf"]
    assert row["attachments"][0]["id"] == celebret.pk


def test_complement_requires_a_motive(world):
    candidate = _declare(world)
    with pytest.raises(ApplicationError):
        person_verification_decide(actor=world.chancelier, person=candidate, decision="complement", note="  ")


def test_complement_notifies_the_person_and_stays_in_queue(world, django_capture_on_commit_callbacks):
    candidate = _declare(world)

    with django_capture_on_commit_callbacks(execute=True):
        response = client_for(world.chancelier).post(
            f"{VERIFICATIONS}{candidate.pk}/decision/",
            {"decision": "complement", "note": "Joindre la lettre d'obédience du provincial."},
            format="json",
        )

    assert response.status_code == 200
    assert response.data["statut_verification"] == StatutVerification.COMPLEMENT
    assert response.data["verification_note"] == "Joindre la lettre d'obédience du provincial."
    assert Notification.objects.filter(user=candidate, event_type="personnes.complement").exists()
    email = Email.objects.get(to=candidate.email)
    assert "obédience" not in email.html  # le motif reste dans l'application
    assert AuditEvent.objects.filter(action="personne.verification", metadata__decision="complement").exists()
    queue = client_for(world.chancelier).get(VERIFICATIONS, {"statut": "complement"}).data
    assert [r["id"] for r in queue["results"]] == [str(candidate.pk)]
    assert client_for(world.chancelier).get(VERIFICATIONS, {"statut": "declare"}).data["count"] == 0


def test_complement_api_without_motive_is_a_400(world):
    candidate = _declare(world)
    response = client_for(world.chancelier).post(
        f"{VERIFICATIONS}{candidate.pk}/decision/", {"decision": "complement"}, format="json"
    )
    assert response.status_code == 400


def test_person_completes_the_declaration(world):
    candidate = _declare(world)
    person_verification_decide(
        actor=world.chancelier, person=candidate, decision="complement", note="Lettre manquante."
    )
    lettre = FileFactory.create(uploaded_by=candidate, original_file_name="lettre-provincial.pdf")

    response = client_for(candidate).post(
        "/api/v1/me/declaration/",
        {
            "etat_de_vie": "clerc",
            "degre_ordre": "pretre",
            "incardination_node_id": str(world.dakar.pk),
            "attachment_file_ids": [lettre.pk],
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["statut_verification"] == StatutVerification.DECLARE
    assert [a["file_name"] for a in response.data["attachments"]] == ["lettre-provincial.pdf"]


def test_me_declaration_shows_the_complement_request(world):
    candidate = _declare(world)
    person_verification_decide(
        actor=world.chancelier, person=candidate, decision="complement", note="Lettre manquante."
    )

    data = client_for(candidate).get("/api/v1/me/declaration/").data

    assert data["statut_verification"] == "complement"
    assert data["verification_note"] == "Lettre manquante."


def test_verifications_are_forbidden_without_personnes_verifier(world):
    assert client_for(world.cure).get(VERIFICATIONS).status_code == 403


def test_account_deletion_forgets_the_attachments(world):
    from apps.files.models import File
    from apps.users.services_privacy import account_delete

    candidate = person(verified=False)
    celebret = FileFactory.create(uploaded_by=candidate)
    person_declaration_submit(
        person=candidate, etat_de_vie="clerc", degre_ordre="pretre", attachment_file_ids=[celebret.pk]
    )

    account_delete(user=candidate)

    assert not DeclarationAttachment.objects.filter(person=candidate).exists()
    assert not File.objects.filter(pk=celebret.pk).exists()
