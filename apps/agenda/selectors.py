import datetime
from typing import Any

from django.db.models import Count, Exists, OuterRef, Q, QuerySet
from django.utils import timezone

from apps.agenda.models import Event, EventRegistration
from apps.core.exceptions import NotFoundError
from apps.hierarchy import authz
from apps.hierarchy.models import Node

_RELATED = ("scope_node", "scope_place", "organizer", "organizer__profile")


def _annotate(qs: QuerySet[Event], *, viewer: Any = None) -> QuerySet[Event]:
    qs = qs.annotate(registrations_count=Count("registrations", distinct=True))
    if viewer is not None and getattr(viewer, "is_authenticated", False):
        qs = qs.annotate(is_registered=Exists(EventRegistration.objects.filter(event=OuterRef("pk"), user=viewer)))
    return qs


def event_list_public(
    *,
    node: Node | None = None,
    date_from: datetime.datetime | None = None,
    date_to: datetime.datetime | None = None,
    event_type: str | None = None,
    viewer: Any = None,
) -> QuerySet[Event]:
    """Événements à venir, non annulés ; ``node`` = ce nœud et son sous-arbre."""
    qs = Event.objects.filter(cancelled_at__isnull=True, end_at__gte=date_from or timezone.now()).select_related(*_RELATED)
    if node is not None:
        qs = qs.filter(scope_node__path__startswith=node.path)
    if date_to is not None:
        qs = qs.filter(start_at__lte=date_to)
    if event_type:
        qs = qs.filter(event_type=event_type)
    return _annotate(qs, viewer=viewer).order_by("start_at")


def event_get_public(*, event_id: int, viewer: Any = None) -> Event:
    try:
        return _annotate(Event.objects.select_related(*_RELATED), viewer=viewer).get(pk=event_id)
    except Event.DoesNotExist as exc:
        raise NotFoundError("Événement introuvable.", {"event_id": event_id}) from exc


def event_list_for_staff(*, user: Any, filters: dict[str, Any] | None = None) -> QuerySet[Event]:
    filters = filters or {}
    scope = Q(scope_node__in=authz.noeuds_autorises(user, "evenements.gerer"))
    if authz.peut(user, "plateforme.admin", None):
        scope |= Q(scope_node__isnull=True)
    qs = Event.objects.filter(scope).select_related(*_RELATED)
    if node_id := filters.get("node"):
        node = Node.objects.filter(pk=node_id).first()
        if node is None:
            raise NotFoundError("Nœud introuvable.", {"node_id": str(node_id)})
        qs = qs.filter(scope_node__path__startswith=node.path)
    if not filters.get("include_past"):
        qs = qs.filter(end_at__gte=timezone.now())
    return _annotate(qs, viewer=user).order_by("start_at")


def event_get_for_staff(*, user: Any, event_id: int) -> Event:
    try:
        return event_list_for_staff(user=user, filters={"include_past": True}).get(pk=event_id)
    except Event.DoesNotExist as exc:
        raise NotFoundError("Événement introuvable.", {"event_id": event_id}) from exc


def event_registrations(*, event: Event) -> QuerySet[EventRegistration]:
    return EventRegistration.objects.filter(event=event).select_related("user", "user__profile").order_by("registered_at")
