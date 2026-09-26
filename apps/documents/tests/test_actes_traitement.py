"""Traitement par la paroisse : pièces jointes, auteurs, assignation, filtres de la file ;
côté fidèle : libellé du motif et date indicative."""

import datetime
from urllib.parse import parse_qs, urlparse

import pytest
from django.core.files.base import ContentFile
from django.test import override_settings
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.documents.models import DocumentRequest, DocumentSlaSetting
from apps.documents.selectors import queue_for
from apps.documents.services import (
    document_request_add_internal_note,
    document_request_assign,
    document_request_create,
    document_request_process,
)
from apps.documents.tests.factories import ValidFileFactory
from apps.hierarchy.models import AuditEvent
from apps.hierarchy.tests.factories import nominate, person, priest
from apps.messaging.models import Notification
from apps.users.models import Profile

pytestmark = pytest.mark.django_db
S = DocumentRequest.Status

FORM = {
    "document_type": "baptism",
    "reason": "religious_marriage",
    "requester_last_name": "Sène",
    "requester_first_names": "Jean-Baptiste",
    "date_of_birth": datetime.date(1994, 3, 12),
    "place_of_birth": "Dakar",
    "contact_phone": "+221774182690",
    "contact_email": "jb@test.sn",
    "father_last_name": "Sène",
    "mother_last_name": "Ndiaye",
    "sacrament_approximate_date": "1994",
    "sacrament_location": "Saint-Dominique",
    "consent_given": True,
}


@pytest.fixture(autouse=True)
def _media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


def named(user, first: str, last: str):
    Profile.objects.update_or_create(user=user, defaults={"first_name": first, "last_name": last})
    user.refresh_from_db()
    return user


@pytest.fixture
def world(tree):
    tree.fidele = named(person("jb@test.sn"), "Jean-Baptiste", "Sène")
    tree.secretaire = named(person("secretaire@sd.sn"), "Germaine", "Faye")
    tree.cure = named(priest("cure@sd.sn"), "Augustin", "Ndiaye")
    tree.cure_st = priest("cure@st.sn")
    nominate(tree.secretaire, "secretaire_paroissial", tree.saint_dominique)
    nominate(tree.cure, "cure", tree.saint_dominique)
    nominate(tree.cure_st, "cure", tree.sainte_therese)
    return tree


def submit(world, **overrides):
    data = {**FORM, **overrides}
    return document_request_create(requester=world.fidele, target_node=world.saint_dominique, data=data)


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def with_piece(world):
    piece = ValidFileFactory(uploaded_by=world.fidele, original_file_name="cni-sene-jb.pdf")
    piece.file.save("cni-sene-jb.pdf", ContentFile(b"%PDF-1.4 test"), save=True)
    return submit(world, attachment_file_id=piece.pk)


# --- Pièces jointes (écart 1) ---------------------------------------------------------------


def test_processor_sees_attachments_with_a_limited_link(world):
    r = with_piece(world)
    data = client_for(world.secretaire).get(f"/api/v1/staff/documents/{r.pk}/").data

    [piece] = data["attachments"]
    assert piece["name"] == "cni-sene-jb.pdf"
    assert piece["content_type"] == "application/pdf"
    assert piece["size"] == len(b"%PDF-1.4 test")
    assert "token=" in piece["url"] and piece["expires_at"]


def test_link_opens_the_file_and_is_audited(world):
    r = with_piece(world)
    url = client_for(world.secretaire).get(f"/api/v1/staff/documents/{r.pk}/").data["attachments"][0]["url"]

    response = APIClient().get(urlparse(url).path, {"token": parse_qs(urlparse(url).query)["token"][0]})

    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"%PDF-1.4 test"
    assert response["Cache-Control"] == "private, no-store"
    assert AuditEvent.objects.filter(
        action="acte.piece_consultee", target_id=str(r.pk), actor=world.secretaire
    ).exists()


def _link(world, r, user):
    url = client_for(user).get(f"/api/v1/staff/documents/{r.pk}/").data["attachments"][0]["url"]
    parsed = urlparse(url)
    return parsed.path, parse_qs(parsed.query)["token"][0]


def test_link_expires(world):
    r = with_piece(world)
    with freeze_time("2026-09-25 10:00:00"):
        path, token = _link(world, r, world.secretaire)
    with override_settings(DOCUMENTS_ATTACHMENT_URL_TTL=300), freeze_time("2026-09-25 10:06:00"):
        response = APIClient().get(path, {"token": token})
    assert response.status_code == 403


def test_link_is_useless_once_the_office_ends(world):
    r = with_piece(world)
    path, token = _link(world, r, world.secretaire)
    world.secretaire.office_assignments.update(status="terminee")
    from apps.hierarchy import authz

    authz.invalidate_user(world.secretaire.pk)
    assert APIClient().get(path, {"token": token}).status_code == 403


def test_forged_or_foreign_tokens_are_refused(world):
    r = with_piece(world)
    other = with_piece(world)
    path, token = _link(world, r, world.secretaire)
    other_path = path.replace(str(r.pk), str(other.pk)).rsplit("/", 2)[0] + f"/{other.attachments.get().pk}/"

    assert APIClient().get(path, {"token": token + "x"}).status_code == 403
    assert APIClient().get(path).status_code == 403
    assert APIClient().get(other_path, {"token": token}).status_code == 403


def test_attachments_are_never_in_the_requester_view(world):
    r = with_piece(world)
    view = client_for(world.fidele).get(f"/api/v1/documents/requests/{r.pk}/").data
    assert "attachments" not in view and "token" not in str(view)


def test_other_parish_gets_404_on_the_detail(world):
    r = with_piece(world)
    assert client_for(world.cure_st).get(f"/api/v1/staff/documents/{r.pk}/").status_code == 404


# --- Auteurs de l'historique et des notes (écarts 1 et 2) ------------------------------------


def test_history_names_each_author(world):
    r = submit(world)
    document_request_process(request_obj=r, actor=world.secretaire, action="start_verification")
    history = client_for(world.secretaire).get(f"/api/v1/staff/documents/{r.pk}/").data["history"]

    assert [(h["to_status"], h["changed_by_name"], h["by_requester"]) for h in history] == [
        (S.SUBMITTED, "Jean-Baptiste Sène", True),
        (S.UNDER_VERIFICATION, "Germaine Faye", False),
    ]
    logs = client_for(world.secretaire).get(f"/api/v1/staff/documents/{r.pk}/logs/").data
    assert logs[1]["changed_by_name"] == "Germaine Faye"


def test_requester_history_hides_the_team_names(world):
    r = submit(world)
    document_request_process(request_obj=r, actor=world.secretaire, action="start_verification")
    view = client_for(world.fidele).get(f"/api/v1/documents/requests/{r.pk}/").data
    assert "Germaine" not in str(view) and "changed_by_name" not in view["history"][0]


def test_notes_carry_the_author_name_and_stay_hidden_from_the_requester(world):
    r = submit(world)
    document_request_add_internal_note(request_obj=r, author=world.cure, content="Mention de confirmation recopiée.")

    notes = client_for(world.secretaire).get(f"/api/v1/staff/documents/{r.pk}/notes/").data
    fidele_detail = client_for(world.fidele).get(f"/api/v1/documents/requests/{r.pk}/")
    fidele_list = client_for(world.fidele).get("/api/v1/documents/requests/")
    fidele_notes = client_for(world.fidele).get(f"/api/v1/staff/documents/{r.pk}/notes/")

    assert [(n["author_name"], n["content"]) for n in notes] == [
        ("Augustin Ndiaye", "Mention de confirmation recopiée.")
    ]
    assert "Mention de confirmation" not in str(fidele_detail.data) + str(fidele_list.data)
    assert fidele_notes.status_code == 403


# --- Assignation (écart 3) -------------------------------------------------------------------


def test_assign_to_a_team_member_is_audited_and_notified(world, django_capture_on_commit_callbacks):
    r = submit(world)
    with django_capture_on_commit_callbacks(execute=True):
        response = client_for(world.cure).post(
            f"/api/v1/staff/documents/{r.pk}/assign/", {"assignee_id": str(world.secretaire.pk)}, format="json"
        )

    assert response.status_code == 200
    assert response.data["assigned_to_id"] == str(world.secretaire.pk)
    assert response.data["assigned_to_name"] == "Germaine Faye"
    assert response.data["status"] == S.SUBMITTED
    event = AuditEvent.objects.get(action="acte.assignation", target_id=str(r.pk))
    assert event.actor == world.cure and event.metadata["to"] == str(world.secretaire.pk)
    assert Notification.objects.filter(user=world.secretaire, event_type="documents.assigned").exists()


def test_unassign(world):
    r = submit(world)
    document_request_assign(request_obj=r, actor=world.cure, assignee=world.secretaire)
    response = client_for(world.cure).post(
        f"/api/v1/staff/documents/{r.pk}/assign/", {"assignee_id": None}, format="json"
    )
    assert response.status_code == 200 and response.data["assigned_to_id"] is None


def test_assignee_must_process_the_same_parish(world):
    r = submit(world)
    with pytest.raises(ApplicationError) as exc:
        document_request_assign(request_obj=r, actor=world.secretaire, assignee=world.cure_st)
    assert exc.value.code == "assignee_not_processor"
    with pytest.raises(ApplicationError):
        document_request_assign(request_obj=r, actor=world.secretaire, assignee=world.fidele)


def test_assign_outside_the_queue_is_refused(world):
    r = submit(world)
    with pytest.raises(PermissionDeniedError):
        document_request_assign(request_obj=r, actor=world.cure_st, assignee=world.cure_st)
    api = client_for(world.cure_st).post(
        f"/api/v1/staff/documents/{r.pk}/assign/", {"assignee_id": None}, format="json"
    )
    assert api.status_code == 404
    assert (
        client_for(world.fidele).post(f"/api/v1/staff/documents/{r.pk}/assign/", {}, format="json").status_code == 403
    )
    assert APIClient().post(f"/api/v1/staff/documents/{r.pk}/assign/", {}, format="json").status_code == 401


def test_assign_validation_and_closed_requests(world):
    r = submit(world)
    staff = client_for(world.secretaire)
    assert staff.post(f"/api/v1/staff/documents/{r.pk}/assign/", {}, format="json").status_code == 400
    unknown = staff.post(
        f"/api/v1/staff/documents/{r.pk}/assign/",
        {"assignee_id": "00000000-0000-0000-0000-000000000000"},
        format="json",
    )
    assert unknown.status_code == 404
    document_request_process(request_obj=r, actor=world.secretaire, action="start_verification")
    document_request_process(request_obj=r, actor=world.secretaire, action="reject", message="Hors registre.")
    r.refresh_from_db()
    with pytest.raises(ApplicationError) as exc:
        document_request_assign(request_obj=r, actor=world.secretaire, assignee=world.cure)
    assert exc.value.code == "request_closed"


def test_assignment_does_not_reset_the_sla_clock(world):
    with freeze_time("2026-09-01 09:00:00"):
        r = submit(world)
    with freeze_time("2026-09-05 09:00:00"):
        document_request_assign(request_obj=r, actor=world.secretaire, assignee=world.cure)
    r.refresh_from_db()
    assert r.updated_at.date() == datetime.date(2026, 9, 1)


def test_assignees_are_the_parish_team(world):
    r = submit(world)
    rows = client_for(world.secretaire).get(f"/api/v1/staff/documents/{r.pk}/assignees/").data
    assert {row["full_name"] for row in rows} == {"Germaine Faye", "Augustin Ndiaye"}
    assert client_for(world.cure_st).get(f"/api/v1/staff/documents/{r.pk}/assignees/").status_code == 404


# --- File : motif, assigné, filtres (écart 3) ------------------------------------------------


def test_queue_item_exposes_reason_and_assignee_name(world):
    r = submit(world)
    document_request_assign(request_obj=r, actor=world.cure, assignee=world.secretaire)
    [item] = client_for(world.secretaire).get("/api/v1/staff/documents/").data["results"]
    assert item["reason"] == "religious_marriage" and item["reason_label"] == "Mariage religieux"
    assert item["assigned_to_name"] == "Germaine Faye"


def test_queue_filters_reason_assignee_and_period(world):
    with freeze_time("2026-09-01 09:00:00"):
        old = submit(world, reason="personal")
    with freeze_time("2026-09-20 09:00:00"):
        mine = submit(world)
        theirs = submit(world)
    document_request_assign(request_obj=mine, actor=world.secretaire, assignee=world.secretaire)
    document_request_assign(request_obj=theirs, actor=world.secretaire, assignee=world.cure)

    def ids(**filters):
        return {r.pk for r in queue_for(user=world.secretaire, filters=filters)}

    assert ids(reason="personal") == {old.pk}
    assert ids(assignee="me") == {mine.pk}
    assert ids(assignee="none") == {old.pk}
    assert ids(assignee=str(world.cure.pk)) == {theirs.pk}
    assert ids(received_from=datetime.date(2026, 9, 10)) == {mine.pk, theirs.pk}
    assert ids(received_to=datetime.date(2026, 9, 10)) == {old.pk}


def test_queue_filter_validation(world):
    staff = client_for(world.secretaire)
    assert staff.get("/api/v1/staff/documents/", {"assignee": "quelqu-un"}).status_code == 400
    assert staff.get("/api/v1/staff/documents/", {"reason": "inconnu"}).status_code == 400
    period = staff.get("/api/v1/staff/documents/", {"received_from": "2026-09-10", "received_to": "2026-09-01"})
    assert period.status_code == 400
    assert staff.get("/api/v1/staff/documents/", {"assignee": "me", "received_from": "2026-09-01"}).status_code == 200


def test_queue_listing_with_names_stays_bounded(world, django_assert_max_num_queries):
    for _ in range(6):
        document_request_assign(request_obj=submit(world), actor=world.secretaire, assignee=world.cure)
    with django_assert_max_num_queries(12):
        response = client_for(world.secretaire).get("/api/v1/staff/documents/")
    assert response.data["count"] == 6


# --- Côté fidèle : motif et date indicative (écart 4) ----------------------------------------


@override_settings(DOCUMENTS_DEFAULT_INDICATIVE_DAYS=7)
def test_requester_sees_reason_label_and_indicative_date(world):
    with freeze_time("2026-09-21 10:00:00"):
        r = submit(world)
        view = client_for(world.fidele).get(f"/api/v1/documents/requests/{r.pk}/").data
    assert view["reason_label"] == "Mariage religieux"
    assert view["indicative_days"] == 7
    assert view["estimated_ready_on"] == datetime.date(2026, 9, 28)


def test_indicative_days_come_from_the_closest_setting(world):
    DocumentSlaSetting.objects.create(node=world.dakar, indicative_days=10)
    with freeze_time("2026-09-21 10:00:00"):
        r = submit(world)
        view = client_for(world.fidele).get(f"/api/v1/documents/requests/{r.pk}/").data
    assert view["indicative_days"] == 10 and view["estimated_ready_on"] == datetime.date(2026, 10, 1)


def test_parish_delay_setting_wins_over_inherited_sla(world):
    # Arrange : le diocèse annonce 10 jours, la paroisse règle elle-même 4 jours (Paramètres).
    DocumentSlaSetting.objects.create(node=world.dakar, indicative_days=10)
    world.saint_dominique.acts_delay_days = 4
    world.saint_dominique.save(update_fields=["acts_delay_days"])

    # Act
    with freeze_time("2026-09-21 10:00:00"):
        r = submit(world)
        view = client_for(world.fidele).get(f"/api/v1/documents/requests/{r.pk}/").data

    # Assert
    assert view["indicative_days"] == 4 and view["estimated_ready_on"] == datetime.date(2026, 9, 25)


def test_indicative_date_is_never_in_the_past_and_disappears_once_ready(world):
    with freeze_time("2026-09-01 10:00:00"):
        r = submit(world)
    with freeze_time("2026-09-25 10:00:00"):
        assert client_for(world.fidele).get(f"/api/v1/documents/requests/{r.pk}/").data[
            "estimated_ready_on"
        ] == datetime.date(2026, 9, 25)
        document_request_process(request_obj=r, actor=world.secretaire, action="start_verification")
        document_request_process(request_obj=r, actor=world.secretaire, action="mark_ready")
        assert client_for(world.fidele).get(f"/api/v1/documents/requests/{r.pk}/").data["estimated_ready_on"] is None


def test_email_plain_text_has_no_html_tags():
    from apps.documents.services import html_to_text

    text = html_to_text("<p>Bonjour Awa,</p><p>La paroisse a besoin d&#x27;un complément.<br>Merci.</p>")

    assert "<" not in text and ">" not in text
    assert text == "Bonjour Awa,\n\nLa paroisse a besoin d'un complément.\nMerci."
