"""Lectures des demandes d'actes V1 (SRS §3.6)."""

import datetime
import statistics
from typing import Any

from django.db.models import Count, Prefetch, Q, QuerySet
from django.utils import timezone

from apps.core.exceptions import NotFoundError
from apps.documents.models import DocumentRequest, DocumentRequestAttachment, DocumentRequestStatusLog, InternalNote
from apps.documents.services import SLA_KEY_BY_STATUS, SlaResolver
from apps.hierarchy import authz
from apps.hierarchy.models import Node

_RELATED = ("requester", "assigned_to", "assigned_to__profile", "target_node", "target_node__type", "pickup_place")


# --- Fidèle -------------------------------------------------------------------------------


def request_list_for_requester(*, user: Any, status: str | None = None) -> QuerySet[DocumentRequest]:
    qs = DocumentRequest.objects.filter(requester=user).select_related(*_RELATED)
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-created_at")


def request_get_for_requester(*, user: Any, request_id: Any) -> DocumentRequest:
    try:
        return (
            DocumentRequest.objects.select_related(*_RELATED)
            .prefetch_related(
                Prefetch("status_logs", queryset=DocumentRequestStatusLog.objects.order_by("created_at")),
                Prefetch("attachments", queryset=DocumentRequestAttachment.objects.select_related("file")),
            )
            .get(pk=request_id, requester=user)
        )
    except (DocumentRequest.DoesNotExist, ValueError) as exc:
        raise NotFoundError("Demande introuvable.", {"request_id": str(request_id)}) from exc


# --- Paroisse --------------------------------------------------------------------------------


def _node_filter(qs: QuerySet[DocumentRequest], node_id: Any) -> QuerySet[DocumentRequest]:
    if not node_id:
        return qs
    node = Node.objects.filter(pk=node_id).first()
    if node is None:
        raise NotFoundError("Nœud introuvable.", {"node_id": str(node_id)})
    return qs.filter(target_node__path__startswith=node.path)


def queue_for(*, user: Any, filters: dict[str, Any] | None = None) -> QuerySet[DocumentRequest]:
    """File de traitement (EF-ACT-03) : demandes adressées aux nœuds où ``user`` a ``actes.traiter``."""
    filters = filters or {}
    qs = DocumentRequest.objects.filter(target_node__in=authz.noeuds_autorises(user, "actes.traiter")).select_related(
        *_RELATED
    )
    qs = _node_filter(qs, filters.get("node"))
    if status := filters.get("status"):
        qs = qs.filter(status=status)
    if document_type := filters.get("document_type"):
        qs = qs.filter(document_type=document_type)
    if search := filters.get("search"):
        qs = qs.filter(
            Q(reference__icontains=search)
            | Q(requester_last_name__icontains=search)
            | Q(requester_first_names__icontains=search)
        )
    if reason := filters.get("reason"):
        qs = qs.filter(reason=reason)
    assignee = filters.get("assignee")
    if assignee == "me":
        qs = qs.filter(assigned_to=user)
    elif assignee == "none":
        qs = qs.filter(assigned_to__isnull=True)
    elif assignee:
        qs = qs.filter(assigned_to_id=assignee)
    if received_from := filters.get("received_from"):
        qs = qs.filter(created_at__date__gte=received_from)
    if received_to := filters.get("received_to"):
        qs = qs.filter(created_at__date__lte=received_to)
    if filters.get("overdue"):
        qs = qs.filter(pk__in=overdue_ids(qs))
    return qs.order_by("-created_at")


def overdue_ids(qs: QuerySet[DocumentRequest], *, now: datetime.datetime | None = None) -> list[Any]:
    """Demandes en retard : une requête (colonnes utiles seulement) + réglages SLA en mémoire."""
    now = now or timezone.now()
    resolver = SlaResolver()
    rows = qs.filter(status__in=list(SLA_KEY_BY_STATUS)).values_list("pk", "status", "updated_at", "target_node__path")
    return [
        pk
        for pk, status, updated_at, path in rows
        if (now - updated_at).days >= resolver.for_path(path)[SLA_KEY_BY_STATUS[status]]
    ]


def request_get_for_processor(*, user: Any, request_id: Any) -> DocumentRequest:
    """404 hors de la file : on ne révèle pas l'existence d'une demande d'une autre paroisse."""
    try:
        return (
            queue_for(user=user)
            .prefetch_related(
                Prefetch(
                    "status_logs",
                    queryset=DocumentRequestStatusLog.objects.select_related("changed_by", "changed_by__profile").order_by(
                        "created_at"
                    ),
                ),
                Prefetch(
                    "attachments",
                    queryset=DocumentRequestAttachment.objects.select_related("file").order_by("created_at"),
                ),
            )
            .get(pk=request_id)
        )
    except (DocumentRequest.DoesNotExist, ValueError) as exc:
        raise NotFoundError("Demande introuvable.", {"request_id": str(request_id)}) from exc


def status_counts(*, queryset: QuerySet[DocumentRequest]) -> dict[str, Any]:
    counts = dict.fromkeys(DocumentRequest.Status.values, 0)
    for row in queryset.order_by().values("status").annotate(total=Count("id")):
        counts[row["status"]] = row["total"]
    return {"counts": counts, "total": sum(counts.values())}


def internal_notes(*, request_obj: DocumentRequest) -> QuerySet[InternalNote]:
    return InternalNote.objects.filter(request=request_obj).select_related("author", "author__profile").order_by("created_at")


def status_logs(*, request_obj: DocumentRequest) -> QuerySet[DocumentRequestStatusLog]:
    return (
        DocumentRequestStatusLog.objects.filter(request=request_obj)
        .select_related("request", "changed_by", "changed_by__profile")
        .order_by("created_at")
    )


def assignees_for(*, request_obj: DocumentRequest) -> QuerySet[Any]:
    """Équipe à qui confier la demande : titulaires d'``actes.traiter`` sur la paroisse même."""
    from apps.hierarchy.selectors_offices import capability_holders

    return (
        capability_holders(node=request_obj.target_node, capability="actes.traiter", direct_only=True)
        .filter(is_active=True)
        .select_related("profile")
        .order_by("profile__last_name", "profile__first_name", "email")
    )


# --- SLA ------------------------------------------------------------------------------------


def age_days(request_obj: DocumentRequest, *, now: datetime.datetime | None = None) -> int | None:
    if request_obj.status not in SLA_KEY_BY_STATUS:
        return None
    return max(0, ((now or timezone.now()) - request_obj.updated_at).days)


def is_overdue(
    request_obj: DocumentRequest, *, now: datetime.datetime | None = None, resolver: SlaResolver | None = None
) -> bool:
    days = age_days(request_obj, now=now)
    if days is None:
        return False
    resolver = resolver or SlaResolver()
    return days >= resolver.for_path(request_obj.target_node.path)[SLA_KEY_BY_STATUS[request_obj.status]]


# --- Supervision agrégée (EF-ACT-10) : aucun nom ------------------------------------------


def supervision_stats(*, user: Any, node_id: Any = None) -> dict[str, Any]:
    qs = DocumentRequest.objects.filter(target_node__in=authz.noeuds_autorises(user, "actes.superviser"))
    qs = _node_filter(qs, node_id)
    closed = qs.filter(status="collected", closed_at__isnull=False).values_list("created_at", "closed_at")
    durations = [(end - start).days for start, end in closed if start is not None and end is not None]
    return {
        **status_counts(queryset=qs),
        "median_days_to_collect": statistics.median(durations) if durations else None,
        "overdue": len(overdue_ids(qs)),
    }
