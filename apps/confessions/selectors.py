"""Lectures des rendez-vous de confession. Aucune ne renvoie de contenu : il n'y en a pas."""

import datetime
from typing import Any

from django.db.models import Prefetch, Q, QuerySet
from django.utils import timezone

from apps.confessions.models import ConfessionBooking, ConfessionSlot, ConfessionSlotRule
from apps.core.exceptions import NotFoundError, PermissionDeniedError
from apps.hierarchy import authz
from apps.hierarchy.models import Node

_SLOT_RELATED = ("priest", "priest__profile", "place", "place__node")
PLANNING_DAYS = 28


def _node_get(node_id: Any) -> Node:
    node = Node.objects.filter(pk=node_id).first()
    if node is None:
        raise NotFoundError("Nœud introuvable.", {"node_id": str(node_id)})
    return node


def slots_available(
    *, node_id: Any = None, place_id: Any = None, date_from: datetime.date | None = None
) -> QuerySet[ConfessionSlot]:
    """Créneaux libres à venir d'un nœud (sous-arbre compris) ou d'un lieu."""
    now = timezone.now()
    qs = ConfessionSlot.objects.filter(
        status=ConfessionSlot.Status.LIBRE, starts_at__gt=now, place__is_active=True
    ).select_related(*_SLOT_RELATED)
    if date_from is not None:
        start = datetime.datetime.combine(date_from, datetime.time.min, tzinfo=timezone.get_current_timezone())
        qs = qs.filter(starts_at__gte=max(start, now))
    if node_id:
        qs = qs.filter(place__node__path__startswith=_node_get(node_id).path)
    if place_id:
        qs = qs.filter(place_id=place_id)
    return qs.order_by("starts_at")


def slot_get_free(*, slot_id: Any) -> ConfessionSlot:
    try:
        return ConfessionSlot.objects.select_related(*_SLOT_RELATED).get(pk=slot_id)
    except (ConfessionSlot.DoesNotExist, ValueError) as exc:
        raise NotFoundError("Créneau introuvable.", {"slot_id": str(slot_id)}) from exc


def bookings_for_person(*, user: Any, upcoming_only: bool = False) -> QuerySet[ConfessionBooking]:
    qs = ConfessionBooking.objects.filter(person=user).select_related(
        "slot", "slot__place", "slot__priest", "slot__priest__profile"
    )
    if upcoming_only:
        qs = qs.filter(slot__starts_at__gt=timezone.now())
    return qs.order_by("-slot__starts_at")


def booking_get_for_person(*, user: Any, booking_id: Any) -> ConfessionBooking:
    try:
        return bookings_for_person(user=user).get(pk=booking_id)
    except (ConfessionBooking.DoesNotExist, ValueError) as exc:
        raise NotFoundError("Réservation introuvable.", {"booking_id": str(booking_id)}) from exc


def rules_for_priest(*, user: Any) -> QuerySet[ConfessionSlotRule]:
    return ConfessionSlotRule.objects.filter(priest=user, is_active=True).select_related("place", "place__node")


def rule_get_for_priest(*, user: Any, rule_id: Any) -> ConfessionSlotRule:
    try:
        return rules_for_priest(user=user).get(pk=rule_id)
    except (ConfessionSlotRule.DoesNotExist, ValueError) as exc:
        raise NotFoundError("Règle introuvable.", {"rule_id": str(rule_id)}) from exc


def slot_get_for_priest(*, user: Any, slot_id: Any) -> ConfessionSlot:
    try:
        return ConfessionSlot.objects.select_related(*_SLOT_RELATED).get(pk=slot_id, priest=user)
    except (ConfessionSlot.DoesNotExist, ValueError) as exc:
        raise NotFoundError("Créneau introuvable.", {"slot_id": str(slot_id)}) from exc


def booking_get_for_priest(*, user: Any, booking_id: Any) -> ConfessionBooking:
    try:
        return ConfessionBooking.objects.select_related("slot", "slot__place").get(pk=booking_id, slot__priest=user)
    except (ConfessionBooking.DoesNotExist, ValueError) as exc:
        raise NotFoundError("Réservation introuvable.", {"booking_id": str(booking_id)}) from exc


def planning_for(*, user: Any, node_id: Any = None, date_from: datetime.date | None = None) -> QuerySet[ConfessionSlot]:
    """Planning : ses propres créneaux (``confessions.gerer``) et ceux des nœuds où l'on a
    ``confessions.voir_planning``. La sérialisation n'affiche le nom qu'au prêtre du créneau."""
    can_manage = authz.a_la_capacite(user, "confessions.gerer")
    can_view = authz.a_la_capacite(user, "confessions.voir_planning")
    if not (can_manage or can_view):
        raise PermissionDeniedError("Vous n'avez pas accès au planning des confessions.", code="planning_forbidden")
    scope = Q(priest=user)
    if can_view:
        scope |= Q(place__node__in=authz.noeuds_autorises(user, "confessions.voir_planning"))
    tz = timezone.get_current_timezone()
    start = datetime.datetime.combine(date_from or timezone.localdate(), datetime.time.min, tzinfo=tz)
    qs = ConfessionSlot.objects.filter(
        scope, starts_at__gte=start, starts_at__lt=start + datetime.timedelta(days=PLANNING_DAYS)
    )
    if node_id:
        qs = qs.filter(place__node__path__startswith=_node_get(node_id).path)
    active = ConfessionBooking.objects.filter(
        status__in=[
            ConfessionBooking.Status.RESERVEE,
            ConfessionBooking.Status.HONOREE,
            ConfessionBooking.Status.ABSENT,
        ]
    ).select_related("person", "person__profile")
    return (
        qs.select_related(*_SLOT_RELATED)
        .prefetch_related(Prefetch("bookings", queryset=active, to_attr="active_bookings"))
        .order_by("starts_at")
    )
