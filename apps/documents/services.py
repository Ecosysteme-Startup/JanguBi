"""Demandes d'actes de la V1 (SRS §3.6, §8.1 ; ADR-009).

L'application suit la démarche jusqu'au retrait de l'original, signé et scellé : elle ne
délivre jamais l'acte (RG-03). La demande va à la paroisse du sacrement (RG-02) ; la file
appartient au nœud (RG-04) et se traite sous ``actes.traiter``.
"""

import datetime
import logging
import secrets
from functools import partial
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.documents.constants import allowed_reasons_for, is_reason_allowed
from apps.documents.models import (
    DocumentRequest,
    DocumentRequestAttachment,
    DocumentRequestStatusLog,
    DocumentSlaSetting,
    InternalNote,
)
from apps.hierarchy import authz
from apps.hierarchy.audit import audit_log
from apps.hierarchy.models import Node, PlaceOfWorship

logger = logging.getLogger(__name__)
S = DocumentRequest.Status

# Transitions du cycle (SRS §8.1) : (statut de départ, action) → (statut d'arrivée, acteur).
TRANSITIONS: dict[str, tuple[set[str], str, str]] = {
    "start_verification": ({S.SUBMITTED}, S.UNDER_VERIFICATION, "paroisse"),
    "request_info": ({S.UNDER_VERIFICATION}, S.INFO_REQUESTED, "paroisse"),
    "mark_ready": ({S.UNDER_VERIFICATION}, S.READY_FOR_PICKUP, "paroisse"),
    "mark_collected": ({S.READY_FOR_PICKUP}, S.COLLECTED, "paroisse"),
    "reject": ({S.UNDER_VERIFICATION}, S.REJECTED, "paroisse"),
    "supplement": ({S.INFO_REQUESTED}, S.UNDER_VERIFICATION, "fidele"),
    "cancel": ({S.SUBMITTED, S.INFO_REQUESTED}, S.CANCELLED, "fidele"),
}
CLOSING_STATUSES = frozenset({S.COLLECTED, S.REJECTED, S.CANCELLED})
DEFAULT_SLA = {"escalate_days": 7, "requester_reminder_days": 5, "pickup_reminder_days": 3}

_REQUIRED_DETAILS: dict[str, list[str]] = {
    DocumentRequest.DocumentType.RELIGIOUS_MARRIAGE: ["spouse_full_name_groom", "spouse_full_name_bride"],
    DocumentRequest.DocumentType.GODPARENT: ["celebration_type"],
}

ORIGINAL_NOTICE = (
    "L'acte vous sera remis en original, signé par le curé (ou la personne qu'il mandate) et revêtu du "
    "sceau de la paroisse. Aucun acte n'est délivré par voie numérique."
)


# --- Contrôles -------------------------------------------------------------------------


def _reference() -> str:
    return f"DOC-{datetime.date.today():%Y%m%d}-{secrets.token_hex(3).upper()}"


def _form_check(*, document_type: str, document_type_free: str, reason: str, reason_free: str, details: dict) -> None:
    if document_type == DocumentRequest.DocumentType.OTHER and not document_type_free.strip():
        raise ApplicationError("Précisez le document demandé (« Autre document »).", code="document_type_free_required")
    if reason == DocumentRequest.RequestReason.OTHER and not reason_free.strip():
        raise ApplicationError("Précisez le motif de la demande (« Autre »).", code="reason_free_required")
    if not is_reason_allowed(document_type=document_type, reason=reason):
        labels = dict(DocumentRequest.RequestReason.choices)
        permitted = ", ".join(str(labels[v]) for v in allowed_reasons_for(document_type) if v in labels)
        raise ApplicationError(
            f"Le motif « {labels.get(reason, reason)} » ne correspond pas au document demandé. Motifs possibles : {permitted}.",
            code="reason_not_allowed",
        )
    missing = [f for f in _REQUIRED_DETAILS.get(document_type, []) if not details.get(f)]
    if missing:
        raise ApplicationError("Informations manquantes pour ce document.", {"missing": missing}, code="details_missing")


def _parish_check(node: Node) -> None:
    """RG-02 : la demande va à la paroisse du sacrement, un nœud qui tient les registres."""
    if not node.type.holds_registers:
        raise ApplicationError("Choisissez la paroisse où le sacrement a été célébré.", code="not_a_parish")
    if node.status == "supprime":
        raise ApplicationError("Cette paroisse n'existe plus.", code="parish_deleted")


def processor_check(*, user: Any, request_obj: DocumentRequest) -> None:
    if request_obj.target_node is None or not authz.peut(user, "actes.traiter", request_obj.target_node):
        raise PermissionDeniedError("Cette demande n'est pas dans votre file.", code="not_in_queue")


def _transition(*, request_obj: DocumentRequest, action: str, actor: Any, comment: str = "") -> str:
    sources, target, _who = TRANSITIONS[action]
    if request_obj.status not in sources:
        raise ApplicationError(
            f"Action « {action} » impossible au statut « {request_obj.get_status_display()} ».",
            {"status": request_obj.status, "action": action},
            code="invalid_transition",
        )
    previous = request_obj.status
    request_obj.status = target
    if target in CLOSING_STATUSES:
        request_obj.closed_at = timezone.now()
    DocumentRequestStatusLog.objects.create(
        request=request_obj, from_status=previous, to_status=target, changed_by=actor, comment=comment
    )
    audit_log(
        actor=actor,
        action=f"acte.{action}",
        target=request_obj,
        node=request_obj.target_node,
        metadata={"from": previous, "to": target},
    )
    return previous


# --- Notifications bilatérales (EF-ACT-04) ------------------------------------------------


_REQUESTER_MESSAGES: dict[str, str] = {
    S.SUBMITTED: "Votre demande {ref} a bien été transmise à {parish}.",
    S.UNDER_VERIFICATION: "La paroisse {parish} examine votre demande {ref}.",
    S.INFO_REQUESTED: "La paroisse {parish} a besoin d'un complément pour votre demande {ref}.",
    S.READY_FOR_PICKUP: "Votre acte ({ref}) est prêt à retirer à {parish}.",
    S.COLLECTED: "Votre demande {ref} est close : l'acte a été retiré.",
    S.REJECTED: "Votre demande {ref} n'a pas pu aboutir.",
    S.CANCELLED: "Votre demande {ref} est annulée.",
}


def _notify_requester(request_obj: DocumentRequest, extra: str = "", *, status: str | None = None) -> None:
    """``status`` est figé au moment de la transition : la notification part après commit,
    quand l'objet a pu avancer encore (plusieurs transitions dans une même transaction)."""
    from apps.messaging.services import notification_send

    status = status or request_obj.status
    parish = request_obj.target_node.name if request_obj.target_node else request_obj.parish_name
    message = _REQUESTER_MESSAGES[status].format(ref=request_obj.reference, parish=parish)
    notification_send(
        user=request_obj.requester,
        event_type="documents.status",
        payload={"request_id": str(request_obj.pk), "reference": request_obj.reference, "status": status},
    )
    body = f"<p>Bonjour {request_obj.requester_first_names},</p><p>{message}</p>"
    if extra:
        body += f"<p>{extra}</p>"
    if status == S.READY_FOR_PICKUP:
        body += f"<p>{ORIGINAL_NOTICE}</p>"
    _email(to=request_obj.contact_email, subject=f"[Jàngu Bi] {message}", html=body)


def _notify_parish(request_obj: DocumentRequest, event: str) -> None:
    """L'équipe de la paroisse (titulaires d'actes.traiter sur le nœud même), en in-app."""
    from apps.hierarchy.selectors_offices import capability_holders
    from apps.messaging.services_notifications import people_notify

    if request_obj.target_node is None:
        return
    holders = capability_holders(node=request_obj.target_node, capability="actes.traiter", direct_only=True)
    people_notify(
        user_ids=list(holders.values_list("pk", flat=True)),
        topic="annonces",
        event_type=f"documents.{event}",
        payload={"request_id": str(request_obj.pk), "reference": request_obj.reference},
    )


def _email(*, to: str, subject: str, html: str) -> None:
    from apps.emails.models import Email
    from apps.emails.tasks import email_send as email_send_task

    if not to:
        return
    email = Email.objects.create(to=to, subject=subject[:255], html=html, plain_text=html, status=Email.Status.SENDING)
    transaction.on_commit(partial(email_send_task.delay, email.id))


# --- Fidèle -------------------------------------------------------------------------------


@transaction.atomic
def document_request_create(*, requester: Any, target_node: Node, data: dict[str, Any]) -> DocumentRequest:
    _parish_check(target_node)
    document_type = data["document_type"]
    reason = data["reason"]
    type_free = (data.get("document_type_free") or "").strip()
    reason_free = (data.get("reason_free") or "").strip()
    details = data.get("document_details") or {}
    _form_check(
        document_type=document_type, document_type_free=type_free, reason=reason, reason_free=reason_free, details=details
    )
    if not data.get("consent_given"):
        raise ApplicationError("Le consentement est nécessaire pour transmettre la demande.", code="consent_required")

    from apps.hierarchy.selectors import node_ancestor_of_type

    diocese = node_ancestor_of_type(node=target_node, type_code="diocese")
    request_obj = DocumentRequest.objects.create(
        reference=_reference(),
        requester=requester,
        document_type=document_type,
        document_type_free=type_free if document_type == DocumentRequest.DocumentType.OTHER else "",
        reason=reason,
        reason_free=reason_free if reason == DocumentRequest.RequestReason.OTHER else "",
        requester_last_name=data["requester_last_name"],
        requester_first_names=data["requester_first_names"],
        date_of_birth=data["date_of_birth"],
        place_of_birth=data["place_of_birth"],
        contact_phone=data["contact_phone"],
        contact_email=data["contact_email"],
        registered_last_name=data.get("registered_last_name", ""),
        registered_first_names=data.get("registered_first_names", ""),
        father_last_name=data["father_last_name"],
        mother_last_name=data["mother_last_name"],
        parish_name=target_node.name,
        diocese=diocese.name if diocese else "",
        target_node=target_node,
        sacrament_approximate_date=data["sacrament_approximate_date"],
        sacrament_location=data["sacrament_location"],
        additional_info=data.get("additional_info", ""),
        document_details=details,
        consent_given=True,
        pickup_mode=data.get("pickup_mode") or DocumentRequest.PickupMode.SECRETARIAT,
        status=S.SUBMITTED,
    )
    DocumentRequestStatusLog.objects.create(request=request_obj, from_status="", to_status=S.SUBMITTED, changed_by=requester)
    audit_log(actor=requester, action="acte.depot", target=request_obj, node=target_node)
    if file_id := data.get("attachment_file_id"):
        _attach(request_obj=request_obj, file_id=file_id, uploaded_by=requester)
    transaction.on_commit(partial(_notify_requester, request_obj, status=S.SUBMITTED))
    transaction.on_commit(partial(_notify_parish, request_obj, "submitted"))
    return request_obj


def _attach(*, request_obj: DocumentRequest, file_id: int, uploaded_by: Any) -> DocumentRequestAttachment:
    from apps.files.models import File

    file_obj = File.objects.filter(pk=file_id).first()
    if file_obj is None:
        raise ApplicationError("Fichier introuvable.", {"file_id": file_id}, code="file_not_found")
    if getattr(file_obj, "uploaded_by_id", uploaded_by.pk) != uploaded_by.pk:
        raise PermissionDeniedError("Ce fichier ne vous appartient pas.", code="file_forbidden")
    if not file_obj.is_valid:
        raise ApplicationError("Le fichier n'a pas fini d'être envoyé.", code="file_incomplete")
    return DocumentRequestAttachment.objects.create(
        request=request_obj,
        file=file_obj,
        uploaded_by=uploaded_by,
        attachment_type=DocumentRequest.AttachmentType.USER_SUPPORTING,
    )


def _requester_check(*, request_obj: DocumentRequest, user: Any) -> None:
    if request_obj.requester_id != user.pk:
        raise PermissionDeniedError("Ce n'est pas votre demande.", code="not_owner")


@transaction.atomic
def document_request_submit_supplement(
    *, request_obj: DocumentRequest, requester: Any, additional_info: str = "", document_details: dict | None = None,
    attachment_file_id: int | None = None,
) -> DocumentRequest:
    _requester_check(request_obj=request_obj, user=requester)
    if not (additional_info.strip() or document_details or attachment_file_id):
        raise ApplicationError("Le complément est vide.", code="empty_supplement")
    _transition(request_obj=request_obj, action="supplement", actor=requester, comment="Complément fourni par le demandeur.")
    if additional_info.strip():
        stamp = timezone.localtime().strftime("%d/%m/%Y %H:%M")
        request_obj.additional_info = f"{request_obj.additional_info}\n\n[Complément du {stamp}]\n{additional_info}".strip()
    if document_details:
        request_obj.document_details = {**request_obj.document_details, **document_details}
    request_obj.save()
    if attachment_file_id:
        _attach(request_obj=request_obj, file_id=attachment_file_id, uploaded_by=requester)
    transaction.on_commit(partial(_notify_parish, request_obj, "supplement"))
    return request_obj


@transaction.atomic
def document_request_cancel(*, request_obj: DocumentRequest, requester: Any) -> DocumentRequest:
    """EF-ACT-07 : annulation par le fidèle tant que la demande est soumise ou en complément."""
    _requester_check(request_obj=request_obj, user=requester)
    _transition(request_obj=request_obj, action="cancel", actor=requester)
    request_obj.save()
    transaction.on_commit(partial(_notify_parish, request_obj, "cancelled"))
    return request_obj


# --- Paroisse ------------------------------------------------------------------------------


@transaction.atomic
def document_request_process(
    *,
    request_obj: DocumentRequest,
    actor: Any,
    action: str,
    message: str = "",
    pickup_place: PlaceOfWorship | None = None,
    pickup_hours: str = "",
) -> DocumentRequest:
    """Transitions de la paroisse : start_verification, request_info, mark_ready, mark_collected, reject."""
    if action not in TRANSITIONS or TRANSITIONS[action][2] != "paroisse":
        raise ApplicationError("Action inconnue.", {"action": action}, code="unknown_action")
    processor_check(user=actor, request_obj=request_obj)
    if action == "reject" and not message.strip():
        raise ApplicationError("Le motif du rejet est obligatoire.", code="reason_required")
    if action == "request_info" and not message.strip():
        raise ApplicationError("Précisez le complément attendu.", code="message_required")
    if action == "mark_ready":
        if pickup_place is not None and pickup_place.node_id != request_obj.target_node_id:
            raise ApplicationError("Le lieu de retrait doit être un lieu de la paroisse.", code="place_not_in_node")
        request_obj.pickup_place = pickup_place
        request_obj.pickup_hours = pickup_hours
        request_obj.pickup_message = message
    if action == "reject":
        request_obj.rejection_reason = message
    if action in {"start_verification", "request_info", "mark_ready"} and request_obj.assigned_to_id is None:
        request_obj.assigned_to = actor
    _transition(request_obj=request_obj, action=action, actor=actor, comment=message)
    request_obj.last_reminded_at = None
    request_obj.save()
    transaction.on_commit(
        partial(_notify_requester, request_obj, message if action != "mark_ready" else "", status=request_obj.status)
    )
    return request_obj


@transaction.atomic
def document_request_register_ref_set(*, request_obj: DocumentRequest, actor: Any, data: dict[str, str]) -> DocumentRequest:
    """EF-ACT-05 : références du registre, visibles de la paroisse seulement."""
    processor_check(user=actor, request_obj=request_obj)
    fields = ["register_volume", "register_page", "register_number", "register_marginal_notes"]
    for field in fields:
        if field in data:
            setattr(request_obj, field, data[field])
    request_obj.save(update_fields=[*fields, "updated_at"])
    audit_log(actor=actor, action="acte.registre", target=request_obj, node=request_obj.target_node)
    return request_obj


@transaction.atomic
def document_request_add_internal_note(*, request_obj: DocumentRequest, author: Any, content: str) -> InternalNote:
    processor_check(user=author, request_obj=request_obj)
    if not content.strip():
        raise ApplicationError("La note est vide.", code="empty_note")
    return InternalNote.objects.create(request=request_obj, author=author, content=content)


# --- SLA, relances, purge (EF-ACT-08, -09) -------------------------------------------------


def sla_for_node(node: Node | None) -> dict[str, int]:
    """Réglage du plus proche ancêtre (ou du nœud), sinon les valeurs par défaut."""
    if node is None:
        return dict(DEFAULT_SLA)
    from apps.hierarchy.selectors import node_ancestors

    lineage = [node, *reversed(list(node_ancestors(node=node)))]
    settings_by_node = {s.node_id: s for s in DocumentSlaSetting.objects.filter(node__in=lineage)}
    for candidate in lineage:
        setting = settings_by_node.get(candidate.pk)
        if setting is not None:
            return {
                "escalate_days": setting.escalate_days,
                "requester_reminder_days": setting.requester_reminder_days,
                "pickup_reminder_days": setting.pickup_reminder_days,
            }
    return dict(DEFAULT_SLA)


SLA_KEY_BY_STATUS: dict[str, str] = {
    S.SUBMITTED: "escalate_days",
    S.UNDER_VERIFICATION: "escalate_days",
    S.INFO_REQUESTED: "requester_reminder_days",
    S.READY_FOR_PICKUP: "pickup_reminder_days",
}


def document_requests_remind(*, now: datetime.datetime | None = None) -> int:
    """Relance quotidienne : la paroisse (soumise / en vérification), le fidèle (complément,
    retrait). Au plus une relance par seuil écoulé (``last_reminded_at``)."""
    now = now or timezone.now()
    count = 0
    open_requests = DocumentRequest.objects.filter(status__in=SLA_KEY_BY_STATUS).select_related(
        "target_node", "requester"
    )
    for request_obj in open_requests.iterator():
        days = sla_for_node(request_obj.target_node)[SLA_KEY_BY_STATUS[request_obj.status]]
        threshold = now - datetime.timedelta(days=days)
        if request_obj.updated_at > threshold:
            continue
        if request_obj.last_reminded_at is not None and request_obj.last_reminded_at > threshold:
            continue
        with transaction.atomic():
            if request_obj.status in (S.SUBMITTED, S.UNDER_VERIFICATION):
                _notify_parish(request_obj, "overdue")
            else:
                _notify_requester(request_obj, "Rappel : votre demande attend une action de votre part.", status=request_obj.status)
            DocumentRequest.objects.filter(pk=request_obj.pk).update(last_reminded_at=now)
        count += 1
    return count


@transaction.atomic
def document_attachments_purge(*, now: datetime.datetime | None = None, retention_days: int = 90) -> int:
    """RG-12 : pièces justificatives supprimées 90 jours après la clôture ; journalisé."""
    now = now or timezone.now()
    due = DocumentRequest.objects.select_for_update(skip_locked=True).filter(
        closed_at__lte=now - datetime.timedelta(days=retention_days), attachments_purged_at__isnull=True
    )
    purged = 0
    for request_obj in due:
        attachments = list(request_obj.attachments.select_related("file"))
        files = [a.file for a in attachments]
        DocumentRequestAttachment.objects.filter(pk__in=[a.pk for a in attachments]).delete()
        for file_obj in files:
            if not DocumentRequestAttachment.objects.filter(file=file_obj).exists():
                file_obj.delete()
        request_obj.attachments_purged_at = now
        request_obj.save(update_fields=["attachments_purged_at"])
        audit_log(
            actor=None,
            action="acte.purge_pieces",
            target=request_obj,
            node=request_obj.target_node,
            metadata={"pieces": len(attachments)},
        )
        purged += 1
    return purged
