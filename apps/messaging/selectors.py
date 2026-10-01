from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from django.db import models
from django.db.models import Count, OuterRef, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce

from apps.messaging.models import (
    Conversation,
    ConversationExport,
    Message,
    MessageBlock,
    MessagingCguAcceptance,
    Notification,
)
from apps.users.models import BaseUser

if TYPE_CHECKING:
    from apps.users.models import BaseUser


def conversation_list(*, user: BaseUser, search: str | None = None) -> QuerySet[Conversation]:
    unread_subquery = (
        Message.objects.filter(
            conversation=OuterRef("pk"),
            read_at__isnull=True,
            deleted_at__isnull=True,
        )
        .exclude(sender=user)
        .values("conversation")
        .annotate(cnt=Count("id"))
        .values("cnt")
    )

    qs = (
        Conversation.objects.filter(Q(participant_a=user) | Q(participant_b=user))
        .annotate(
            unread_count=Coalesce(
                Subquery(unread_subquery),
                0,
                output_field=models.IntegerField(),
            )
        )
        .select_related(
            "participant_a",
            "participant_a__profile",
            "participant_b",
            "participant_b__profile",
        )
        .order_by(models.F("last_message_at").desc(nulls_last=True))
    )

    if search:
        # Filtre sur le nom/email des participants. On ne peut pas exclure
        # proprement le user courant du match (il est l'un des deux côtés) mais
        # chercher son propre nom est un cas marginal sans conséquence.
        qs = qs.filter(
            Q(participant_a__email__icontains=search)
            | Q(participant_a__profile__first_name__icontains=search)
            | Q(participant_a__profile__last_name__icontains=search)
            | Q(participant_b__email__icontains=search)
            | Q(participant_b__profile__first_name__icontains=search)
            | Q(participant_b__profile__last_name__icontains=search)
        )

    return qs


def messaging_cgu_get(*, user: BaseUser) -> Optional[MessagingCguAcceptance]:
    return MessagingCguAcceptance.objects.filter(user=user).first()


def conversation_get(*, conversation_id: UUID, user: BaseUser) -> Optional[Conversation]:
    return (
        Conversation.objects.filter(pk=conversation_id)
        .filter(Q(participant_a=user) | Q(participant_b=user))
        .select_related(
            "participant_a",
            "participant_a__profile",
            "participant_b",
            "participant_b__profile",
        )
        .first()
    )


def message_list(
    *,
    conversation: Conversation,
    before_id: Optional[UUID] = None,
    limit: int = 30,
) -> QuerySet[Message]:
    qs = (
        Message.objects.filter(conversation=conversation)
        .select_related("sender", "sender__profile", "reply_to")
        .prefetch_related("attachments__file", "reactions")
        .order_by("-created_at")
    )
    if before_id is not None:
        try:
            pivot = Message.objects.get(id=before_id)
            qs = qs.filter(created_at__lt=pivot.created_at)
        except Message.DoesNotExist:
            pass
    return qs[:limit]


def unread_count(*, conversation: Conversation, user: BaseUser) -> int:
    return (
        Message.objects.filter(
            conversation=conversation,
            read_at__isnull=True,
            deleted_at__isnull=True,
        )
        .exclude(sender=user)
        .count()
    )


def priests_reachable_for(*, user: BaseUser) -> list[dict]:
    """EF-PRE-01 : prêtres joignables de la paroisse suivie (nomination sur ce nœud) et des
    aumôneries du même diocèse, avec leur disponibilité. Sans paroisse suivie : liste vide."""
    from apps.hierarchy.models import Node
    from apps.hierarchy.selectors import node_ancestor_of_type
    from apps.hierarchy.selectors_offices import capability_holders
    from apps.messaging.models import MessagingAvailability

    parish = getattr(user, "paroisse_suivie", None)
    if parish is None:
        return []
    targets = [parish]
    diocese = node_ancestor_of_type(node=parish, type_code="diocese")
    if diocese is not None:
        targets += list(Node.objects.filter(path__startswith=diocese.path, type__code="aumonerie", status="erige"))

    rows: dict = {}
    for node in targets:
        for priest in capability_holders(node=node, capability="messagerie.recevoir_fideles", direct_only=True):
            if priest.pk != user.pk:
                rows.setdefault(priest.pk, {"user": priest, "nodes": []})["nodes"].append(node)
    availabilities = {a.user_id: a for a in MessagingAvailability.objects.filter(user_id__in=list(rows))}
    offices = _principal_offices(person_ids=list(rows), nodes=targets, parish=parish)
    result = []
    for row in rows.values():
        availability = availabilities.get(row["user"].pk)
        if availability is not None and not availability.accepts_new_conversations:
            continue
        result.append({**row, "availability": availability, "office": offices.get(row["user"].pk)})
    return sorted(result, key=lambda r: r["user"].email)


def _principal_offices(*, person_ids: list, nodes: list, parish: Any) -> dict:
    """Office de la nomination active principale de chaque prêtre, parmi les nœuds où il est
    joignable : d'abord la paroisse suivie, puis un office à titulaire unique (curé,
    aumônier) avant un office partagé (vicaire), puis la nomination la plus ancienne."""
    from django.utils import timezone

    from apps.hierarchy.enums import AssignmentStatus, Cardinality
    from apps.hierarchy.models import OfficeAssignment

    if not person_ids:
        return {}
    today = timezone.localdate()
    assignments = (
        OfficeAssignment.objects.filter(
            person_id__in=person_ids,
            node__in=nodes,
            status=AssignmentStatus.ACTIVE,
            start_date__lte=today,
            office_type__capabilities__code="messagerie.recevoir_fideles",
        )
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=today))
        .select_related("office_type")
    )
    offices: dict = {}
    for a in sorted(
        assignments,
        key=lambda a: (a.node_id != parish.pk, a.office_type.cardinality != Cardinality.ONE, a.start_date),
    ):
        offices.setdefault(a.person_id, {"code": a.office_type.code, "label": a.title})
    return offices


def block_list(*, user: BaseUser) -> QuerySet[MessageBlock]:
    return MessageBlock.objects.filter(blocker=user).select_related("blocked")


def export_list(*, conversation: Conversation) -> QuerySet[ConversationExport]:
    return ConversationExport.objects.filter(conversation=conversation).order_by("-created_at")


def notification_list(*, user: BaseUser, unread_only: bool = False) -> QuerySet[Notification]:
    qs = Notification.objects.filter(user=user).order_by("-created_at")
    if unread_only:
        qs = qs.filter(is_read=False)
    return qs
