from __future__ import annotations

from typing import TYPE_CHECKING, Optional
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


def conversation_get(
    *, conversation_id: UUID, user: BaseUser
) -> Optional[Conversation]:
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
    result = []
    for row in rows.values():
        availability = availabilities.get(row["user"].pk)
        if availability is not None and not availability.accepts_new_conversations:
            continue
        result.append({**row, "availability": availability})
    return sorted(result, key=lambda r: r["user"].email)


def block_list(*, user: BaseUser) -> QuerySet[MessageBlock]:
    return MessageBlock.objects.filter(blocker=user).select_related("blocked")


def export_list(*, conversation: Conversation) -> QuerySet[ConversationExport]:
    return ConversationExport.objects.filter(conversation=conversation).order_by(
        "-created_at"
    )


def notification_list(
    *, user: BaseUser, unread_only: bool = False
) -> QuerySet[Notification]:
    qs = Notification.objects.filter(user=user).order_by("-created_at")
    if unread_only:
        qs = qs.filter(is_read=False)
    return qs


# ---------------------------------------------------------------------------
# ClergicalMessage selectors
# ---------------------------------------------------------------------------

def clerical_message_territory_ids(user: "BaseUser") -> dict[str, set[int]]:
    """
    Territoires auxquels `user` appartient, pour la résolution des diffusions.

    Deux sources, réunies volontairement : les affectations de rôle
    (`RoleAssignment`, via `apps.users.scoping`) et les appartenances
    (`Membership`, via `get_scope_ids`). Un curé est rattaché par affectation,
    un religieux ou un diacre peut ne l'être que par appartenance : n'interroger
    qu'une seule des deux sources priverait silencieusement une partie du clergé
    de ses messages.
    """
    from apps.users.scoping import (
        accessible_diocese_ids,
        accessible_parish_ids,
        accessible_province_ids,
    )

    memberships = user.get_scope_ids()

    def _merge(from_roles: set[int] | None, from_memberships: list[int]) -> set[int]:
        # `None` signifie « aucune restriction » (super-admin) côté scoping ; ici
        # on cherche une APPARTENANCE, pas un droit d'administration : un
        # super-admin sans territoire ne reçoit pas les diffusions du clergé.
        return (from_roles or set()) | set(from_memberships)

    return {
        "parish_ids": _merge(accessible_parish_ids(user), memberships["parish_ids"]),
        "diocese_ids": _merge(accessible_diocese_ids(user), memberships["diocese_ids"]),
        "province_ids": _merge(
            accessible_province_ids(user),
            [user.province_id] if user.province_id else [],
        ),
    }


def clerical_message_inbox(*, user: "BaseUser") -> "QuerySet":
    """
    Messages inter-clergé destinés à `user`, diffusions COMPRISES.

    Le filtre ne portait que sur `individual_recipient`. Or trois des quatre
    portées (`parish_clergy`, `diocese_clergy`, `province_bishops`) laissent ce
    champ vide par construction : ces messages étaient écrits en base et
    n'apparaissaient dans AUCUNE boîte de réception. Un évêque diffusant une
    consigne à son diocèse ne recevait aucune erreur, la voyait dans ses
    « envoyés », et personne ne la lisait jamais.
    """
    from django.db.models import Q

    from apps.messaging.models import ClergicalMessage
    from apps.users.enums import CLERGY_PASTORAL_ROLES, PastoralRole

    visible = Q(individual_recipient=user)

    if user.pastoral_role in CLERGY_PASTORAL_ROLES:
        territories = clerical_message_territory_ids(user)

        if territories["parish_ids"]:
            visible |= Q(
                recipient_scope=ClergicalMessage.RecipientScope.PARISH_CLERGY,
                scope_id__in=territories["parish_ids"],
            )
        if territories["diocese_ids"]:
            visible |= Q(
                recipient_scope=ClergicalMessage.RecipientScope.DIOCESE_CLERGY,
                scope_id__in=territories["diocese_ids"],
            )
        # La diffusion aux évêques de province ne s'adresse qu'aux évêques :
        # l'ouvrir à tout le clergé de la province exposerait des échanges
        # d'épiscopat aux prêtres et aux diacres.
        if user.pastoral_role in (PastoralRole.EVEQUE, PastoralRole.ARCHEVEQUE) and territories["province_ids"]:
            visible |= Q(
                recipient_scope=ClergicalMessage.RecipientScope.PROVINCE_BISHOPS,
                scope_id__in=territories["province_ids"],
            )

    return (
        ClergicalMessage.objects.filter(visible)
        .exclude(sender=user)  # ses propres diffusions sont dans « envoyés »
        .select_related("sender")
        .order_by("-created_at")
    )


def clerical_message_sent(*, user: "BaseUser") -> "QuerySet":
    from apps.messaging.models import ClergicalMessage

    return ClergicalMessage.objects.filter(sender=user).select_related("individual_recipient").order_by("-created_at")
