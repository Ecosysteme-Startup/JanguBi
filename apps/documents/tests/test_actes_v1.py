"""Demandes d'actes V1 : cycle §8.1, file par nœud, confidentialité, SLA, purge (SRS §3.6)."""

import datetime

import pytest
from django.core import mail
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.documents.models import DocumentRequest, DocumentRequestAttachment, DocumentSlaSetting
from apps.documents.selectors import is_overdue, queue_for, supervision_stats
from apps.documents.services import (
    document_attachments_purge,
    document_request_add_internal_note,
    document_request_cancel,
    document_request_create,
    document_request_process,
    document_request_register_ref_set,
    document_request_submit_supplement,
    document_requests_remind,
    sla_for_node,
)
from apps.documents.tests.factories import ValidFileFactory
from apps.files.models import File
from apps.hierarchy.models import AuditEvent
from apps.hierarchy.tests.factories import make_place, nominate, person, priest
from apps.messaging.models import Notification

pytestmark = pytest.mark.django_db
S = DocumentRequest.Status

FORM = {
    "document_type": "baptism",
    "reason": "religious_marriage",
    "requester_last_name": "Ndiaye",
    "requester_first_names": "Awa",
    "date_of_birth": datetime.date(1995, 3, 4),
    "place_of_birth": "Dakar",
    "contact_phone": "+221770000000",
    "contact_email": "awa@test.sn",
    "father_last_name": "Ndiaye",
    "mother_last_name": "Faye",
    "sacrament_approximate_date": "1995",
    "sacrament_location": "Saint-Dominique",
    "consent_given": True,
}


@pytest.fixture
def world(tree):
    tree.fidele = person("awa@test.sn")
    tree.secretaire = person("secretaire@sd.sn")
    tree.cure_st = priest("cure@st.sn")
    tree.doyen = priest("doyen@pm.sn")
    nominate(tree.secretaire, "secretaire_paroissial", tree.saint_dominique)
    nominate(tree.cure_st, "cure", tree.sainte_therese)
    nominate(tree.doyen, "doyen", tree.doyenne)
    return tree


def submit(world, **overrides):
    return document_request_create(
        requester=world.fidele, target_node=world.saint_dominique, data={**FORM, **overrides}
    )


def process(world, request_obj, action, **kwargs):
    return document_request_process(request_obj=request_obj, actor=world.secretaire, action=action, **kwargs)


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# --- Dépôt (EF-ACT-01) ----------------------------------------------------------------------


def test_request_goes_to_the_parish_of_the_sacrament(world):
    request_obj = submit(world)
    assert request_obj.target_node == world.saint_dominique
    assert AuditEvent.objects.filter(action="acte.depot", target_id=str(request_obj.pk)).exists()


def test_target_must_hold_registers(world):
    with pytest.raises(ApplicationError) as exc:
        document_request_create(requester=world.fidele, target_node=world.doyenne, data=FORM)
    assert exc.value.code == "not_a_parish"


def test_reason_must_match_the_document(world):
    with pytest.raises(ApplicationError) as exc:
        submit(world, document_type="religious_marriage", reason="godparent")
    assert exc.value.code == "reason_not_allowed"


def test_consent_is_required(world):
    with pytest.raises(ApplicationError):
        submit(world, consent_given=False)


def test_attachment_must_belong_to_the_requester(world):
    other_file = ValidFileFactory(uploaded_by=person())
    with pytest.raises(PermissionDeniedError):
        submit(world, attachment_file_id=other_file.pk)
    own = ValidFileFactory(uploaded_by=world.fidele)
    assert submit(world, attachment_file_id=own.pk).attachments.count() == 1


# --- Cycle §8.1 (EF-ACT-04) -----------------------------------------------------------------


def test_full_cycle_until_collection(world, django_capture_on_commit_callbacks):
    place = make_place(world.saint_dominique, "Secrétariat", kind="eglise_paroissiale", is_main=True)
    with django_capture_on_commit_callbacks(execute=True):
        r = submit(world)
        process(world, r, "start_verification")
        process(world, r, "request_info", message="Merci de préciser l'année exacte.")
        document_request_submit_supplement(request_obj=r, requester=world.fidele, additional_info="Baptisée en 1995.")
        process(world, r, "mark_ready", message="Passez en semaine.", pickup_place=place, pickup_hours="Lun-ven 9h-12h")
        process(world, r, "mark_collected")

    r.refresh_from_db()
    assert r.status == S.COLLECTED and r.closed_at is not None
    assert list(r.status_logs.order_by("created_at").values_list("to_status", flat=True)) == [
        S.SUBMITTED,
        S.UNDER_VERIFICATION,
        S.INFO_REQUESTED,
        S.UNDER_VERIFICATION,
        S.READY_FOR_PICKUP,
        S.COLLECTED,
    ]
    # Notification bilatérale : le fidèle à chaque action de la paroisse (pas pour son propre
    # complément), la paroisse au dépôt et au complément.
    assert Notification.objects.filter(user=world.fidele, event_type="documents.status").count() == 5
    assert Notification.objects.filter(user=world.secretaire, event_type="documents.supplement").exists()
    assert Notification.objects.filter(user=world.secretaire, event_type="documents.submitted").exists()
    ready_mail = next(m for m in mail.outbox if "prêt à retirer" in m.subject)
    assert "signé" in ready_mail.body and "sceau" in ready_mail.body


@pytest.mark.parametrize(
    ("status", "action"),
    [
        (S.SUBMITTED, "mark_ready"),
        (S.SUBMITTED, "reject"),
        (S.INFO_REQUESTED, "mark_collected"),
        (S.READY_FOR_PICKUP, "request_info"),
    ],
)
def test_forbidden_transitions_are_400(world, status, action):
    r = submit(world)
    DocumentRequest.objects.filter(pk=r.pk).update(status=status)
    r.refresh_from_db()
    with pytest.raises(ApplicationError) as exc:
        process(world, r, action, message="x")
    assert exc.value.code == "invalid_transition"


def test_rejection_needs_a_reason(world):
    r = submit(world)
    process(world, r, "start_verification")
    with pytest.raises(ApplicationError):
        process(world, r, "reject")
    r = process(world, r, "reject", message="Aucun acte à ce nom dans nos registres.")
    assert r.status == S.REJECTED and r.closed_at is not None


def test_requester_cancels_only_early(world):
    r = submit(world)
    assert document_request_cancel(request_obj=r, requester=world.fidele).status == S.CANCELLED
    r2 = submit(world)
    process(world, r2, "start_verification")
    with pytest.raises(ApplicationError):
        document_request_cancel(request_obj=r2, requester=world.fidele)


def test_someone_else_cannot_cancel(world):
    with pytest.raises(PermissionDeniedError):
        document_request_cancel(request_obj=submit(world), requester=person())


def test_pickup_place_must_belong_to_the_parish(world):
    r = submit(world)
    process(world, r, "start_verification")
    elsewhere = make_place(world.sainte_therese, "Église Sainte-Thérèse")
    with pytest.raises(ApplicationError):
        process(world, r, "mark_ready", pickup_place=elsewhere)


# --- File par nœud (EF-ACT-03, RG-04) --------------------------------------------------------


def test_queue_is_scoped_to_the_parish(world):
    mine = submit(world)
    other = document_request_create(requester=world.fidele, target_node=world.sainte_therese, data=FORM)

    assert list(queue_for(user=world.secretaire)) == [mine]
    assert list(queue_for(user=world.cure_st)) == [other]
    with pytest.raises(PermissionDeniedError):
        process(world, other, "start_verification")


def test_successor_inherits_the_queue(world):
    r = submit(world)
    new_secretary = person()
    nominate(new_secretary, "secretaire_paroissial", world.saint_dominique)
    assert list(queue_for(user=new_secretary)) == [r]


def test_dean_supervises_without_names(world):
    submit(world)
    stats = supervision_stats(user=world.doyen)
    assert stats["counts"][S.SUBMITTED] == 1 and stats["total"] == 1
    assert list(queue_for(user=world.doyen)) == []


# --- Registre et notes (EF-ACT-02, -05) ------------------------------------------------------


def test_register_refs_and_notes_are_never_shown_to_the_requester(world):
    r = submit(world)
    document_request_register_ref_set(
        request_obj=r,
        actor=world.secretaire,
        data={"register_volume": "B-12", "register_page": "34", "register_number": "567"},
    )
    document_request_add_internal_note(request_obj=r, author=world.secretaire, content="Vérifier la mention marginale.")

    fidele_view = client_for(world.fidele).get(f"/api/v1/documents/requests/{r.pk}/").data
    staff_view = client_for(world.secretaire).get(f"/api/v1/staff/documents/{r.pk}/").data
    notes = client_for(world.secretaire).get(f"/api/v1/staff/documents/{r.pk}/notes/").data

    assert "register" not in fidele_view and "B-12" not in str(fidele_view)
    assert "Vérifier" not in str(fidele_view)
    assert staff_view["register"]["volume"] == "B-12"
    assert [n["content"] for n in notes] == ["Vérifier la mention marginale."]


# --- SLA, relances, purge (EF-ACT-08, -09) ---------------------------------------------------


def test_sla_uses_the_closest_setting(world):
    DocumentSlaSetting.objects.create(node=world.dakar, escalate_days=10)
    DocumentSlaSetting.objects.create(node=world.saint_dominique, escalate_days=2)
    assert sla_for_node(world.saint_dominique)["escalate_days"] == 2
    assert sla_for_node(world.sainte_therese)["escalate_days"] == 10
    assert sla_for_node(world.thies_parish)["escalate_days"] == 7


def test_overdue_reminder_once_per_threshold(world):
    with freeze_time("2026-09-01 09:00:00"):
        r = submit(world)
    with freeze_time("2026-09-09 09:00:00"):
        assert is_overdue(r)
        assert document_requests_remind() == 1
        assert document_requests_remind() == 0
    assert Notification.objects.filter(user=world.secretaire, event_type="documents.overdue").count() == 1


def test_attachments_are_purged_90_days_after_closure(world):
    piece = ValidFileFactory(uploaded_by=world.fidele)
    r = submit(world, attachment_file_id=piece.pk)
    process(world, r, "start_verification")
    process(world, r, "reject", message="Hors registre.")

    with freeze_time(timezone.now() + datetime.timedelta(days=89)):
        assert document_attachments_purge() == 0
    with freeze_time(timezone.now() + datetime.timedelta(days=91)):
        assert document_attachments_purge() == 1

    assert not DocumentRequestAttachment.objects.filter(request=r).exists()
    assert not File.objects.filter(pk=piece.pk).exists()
    assert AuditEvent.objects.filter(action="acte.purge_pieces", target_id=str(r.pk)).exists()


# --- API ---------------------------------------------------------------------------------


def _payload(world, **kw):
    data = {**FORM, "date_of_birth": "1995-03-04", "target_node_id": str(world.saint_dominique.pk), **kw}
    return data


def test_api_requester_flow(world):
    client = client_for(world.fidele)
    created = client.post("/api/v1/documents/requests/", _payload(world), format="json")
    listing = client.get("/api/v1/documents/requests/")
    cancelled = client.post(f"/api/v1/documents/requests/{created.data['id']}/cancel/")

    assert created.status_code == 201 and created.data["status"] == "submitted" and created.data["can_cancel"]
    assert listing.data["count"] == 1
    assert cancelled.data["status"] == "cancelled"


def test_sacrament_date_cannot_precede_birth(world):
    """JB-WEB-028 : la date du sacrement doit être postérieure ou égale à la naissance."""
    client = client_for(world.fidele)
    rejected = client.post(
        "/api/v1/documents/requests/",
        _payload(world, date_of_birth="2011-05-01", sacrament_approximate_date="2005"),
        format="json",
    )
    assert rejected.status_code == 400
    assert "sacrament_approximate_date" in rejected.data["error"]["details"]

    accepted = client.post(
        "/api/v1/documents/requests/",
        _payload(world, date_of_birth="2011-05-01", sacrament_approximate_date="2012"),
        format="json",
    )
    assert accepted.status_code == 201


def test_api_staff_flow_and_404_outside_the_queue(world):
    r = submit(world)
    staff = client_for(world.secretaire)
    started = staff.post(f"/api/v1/staff/documents/{r.pk}/start-verification/", {}, format="json")
    counts = staff.get("/api/v1/staff/documents/counts/")
    outsider = client_for(world.cure_st).get(f"/api/v1/staff/documents/{r.pk}/")
    fidele = client_for(person()).get("/api/v1/staff/documents/")
    stranger_detail = client_for(person()).get(f"/api/v1/documents/requests/{r.pk}/")

    assert started.status_code == 200 and started.data["status"] == "under_verification"
    assert counts.data["counts"]["under_verification"] == 1
    assert outsider.status_code == 404
    assert fidele.status_code == 403
    assert stranger_detail.status_code == 404


def test_api_invalid_transition_is_400(world):
    r = submit(world)
    response = client_for(world.secretaire).post(f"/api/v1/staff/documents/{r.pk}/mark-collected/", {}, format="json")
    assert response.status_code == 400 and response.data["error"]["code"] == "invalid_transition"


def test_api_stats_for_supervisors_only(world):
    submit(world)
    assert client_for(world.doyen).get("/api/v1/staff/documents/stats/").data["total"] == 1
    assert client_for(world.secretaire).get("/api/v1/staff/documents/stats/").status_code == 403


def test_platform_admin_does_not_process_acts(world):
    from apps.users.tests.factories import SuperAdminFactory

    r = submit(world)
    admin = client_for(SuperAdminFactory.create())
    assert admin.get(f"/api/v1/staff/documents/{r.pk}/").status_code == 403


def test_options_endpoint(world):
    data = client_for(world.fidele).get("/api/v1/documents/requests/options/").data
    assert {m["value"] for m in data["pickup_modes"]} == {"secretariat", "transfer_to_followed_parish"}


def test_queue_listing_does_not_query_sla_per_row(world, django_assert_max_num_queries):
    for _ in range(8):
        submit(world)
    client = client_for(world.secretaire)
    with django_assert_max_num_queries(12):
        response = client.get("/api/v1/staff/documents/", {"overdue": "false"})
    assert response.data["count"] == 8


def test_register_refs_do_not_reset_the_sla_clock(world):
    with freeze_time("2026-09-01 09:00:00"):
        r = submit(world)
    with freeze_time("2026-09-05 09:00:00"):
        document_request_register_ref_set(request_obj=r, actor=world.secretaire, data={"register_volume": "B-1"})
    r.refresh_from_db()
    assert r.updated_at.date() == datetime.date(2026, 9, 1)


def test_notifications_go_to_the_account_email_not_the_free_contact(world, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        submit(world, contact_email="autre-personne@test.sn")
    assert [m.to for m in mail.outbox] == [["awa@test.sn"]]


def test_file_without_owner_cannot_be_attached(world):
    orphan = ValidFileFactory(uploaded_by=None)
    with pytest.raises(PermissionDeniedError):
        submit(world, attachment_file_id=orphan.pk)
