from datetime import date
from typing import Any
from uuid import UUID

from django.db.models import Q, QuerySet

from apps.core.exceptions import NotFoundError
from apps.hierarchy.enums import NodeStatus
from apps.hierarchy.models import MassSchedule, Node, NodeType, PlaceOfWorship, ScheduleException
from apps.hierarchy.week import Occurrence, compute_week


def node_type_list() -> QuerySet[NodeType]:
    return NodeType.objects.prefetch_related("allowed_parent_types").order_by("order", "label")


def node_type_get_by_code(*, code: str) -> NodeType:
    try:
        return NodeType.objects.get(code=code)
    except NodeType.DoesNotExist as exc:
        raise NotFoundError(f"Type de nœud « {code} » inconnu.", {"type": code}) from exc


def node_get(*, node_id: UUID | str) -> Node:
    try:
        return Node.objects.select_related("type", "located_in").get(pk=node_id)
    except (Node.DoesNotExist, ValueError) as exc:
        raise NotFoundError("Nœud introuvable.", {"node_id": str(node_id)}) from exc


def node_get_by_code(*, code: str) -> Node:
    try:
        return Node.objects.select_related("type").get(code=code)
    except Node.DoesNotExist as exc:
        raise NotFoundError(f"Nœud « {code} » introuvable.", {"code": code}) from exc


def node_subtree(*, node: Node, include_self: bool = True) -> QuerySet[Node]:
    qs = Node.objects.filter(path__startswith=node.path)
    if not include_self:
        qs = qs.exclude(pk=node.pk)
    return qs


def node_list(*, filters: dict[str, Any] | None = None) -> QuerySet[Node]:
    """Filtres : ``type`` (code), ``parent`` (id), ``q`` (nom/ville/code), ``status``,
    ``within`` (id d'un ancêtre), ``on_platform`` (bool), ``city``. Les nœuds supprimés sont
    exclus sauf si ``status=supprime`` est demandé explicitement."""
    filters = filters or {}
    qs = Node.objects.select_related("type")

    status = filters.get("status")
    qs = qs.filter(status=status) if status else qs.exclude(status=NodeStatus.SUPPRIME)

    if type_code := filters.get("type"):
        qs = qs.filter(type__code=type_code)
    if parent_id := filters.get("parent"):
        parent = node_get(node_id=parent_id)
        qs = qs.filter(path__startswith=parent.path, depth=parent.depth + 1)
    if within_id := filters.get("within"):
        ancestor = node_get(node_id=within_id)
        qs = qs.filter(path__startswith=ancestor.path).exclude(pk=ancestor.pk)
    if city := filters.get("city"):
        qs = qs.filter(city__icontains=city)
    if (on_platform := filters.get("on_platform")) is not None:
        qs = qs.filter(is_active_on_platform=on_platform)
    if q := filters.get("q"):
        qs = qs.filter(Q(name__icontains=q) | Q(city__icontains=q) | Q(code__icontains=q))
    return qs.order_by("type__order", "name")


def node_children(*, node: Node) -> QuerySet[Node]:
    """Enfants directs, en une requête (EF-HIE-03)."""
    return (
        Node.objects.select_related("type")
        .filter(path__startswith=node.path, depth=node.depth + 1)
        .order_by("type__order", "name")
    )


def node_ancestors(*, node: Node) -> QuerySet[Node]:
    """Ancêtres de la racine au parent, en une requête (EF-HIE-03)."""
    paths = [node.path[: node.steplen * i] for i in range(1, node.depth)]
    return Node.objects.select_related("type").filter(path__in=paths).order_by("depth")


def node_ancestor_of_type(*, node: Node, type_code: str) -> Node | None:
    """Premier ancêtre (ou le nœud lui-même) d'un type donné, ex. le diocèse d'une paroisse."""
    if node.type.code == type_code:
        return node
    return node_ancestors(node=node).filter(type__code=type_code).order_by("-depth").first()


# --- Lieux et horaires --------------------------------------------------------


def place_list(*, node: Node, include_inactive: bool = False) -> QuerySet[PlaceOfWorship]:
    qs = PlaceOfWorship.objects.filter(node=node)
    if not include_inactive:
        qs = qs.filter(is_active=True)
    return qs.order_by("-is_main", "name")


def place_get(*, place_id: int) -> PlaceOfWorship:
    try:
        return PlaceOfWorship.objects.select_related("node", "node__type").get(pk=place_id)
    except PlaceOfWorship.DoesNotExist as exc:
        raise NotFoundError("Lieu de culte introuvable.", {"place_id": place_id}) from exc


def schedule_list(*, place: PlaceOfWorship) -> QuerySet[MassSchedule]:
    return MassSchedule.objects.filter(place=place).order_by("weekday", "start_time")


def schedule_exception_list(*, place: PlaceOfWorship, date_from: date | None = None) -> QuerySet[ScheduleException]:
    qs = ScheduleException.objects.filter(place=place)
    if date_from is not None:
        qs = qs.filter(date__gte=date_from)
    return qs.order_by("date", "start_time")


def schedule_exception_get(*, place: PlaceOfWorship, exception_id: int) -> ScheduleException:
    try:
        return ScheduleException.objects.get(pk=exception_id, place=place)
    except ScheduleException.DoesNotExist as exc:
        raise NotFoundError("Exception d'horaire introuvable.", {"exception_id": exception_id}) from exc


def node_week(*, node: Node, start: date, days: int = 7) -> tuple[list[PlaceOfWorship], list[Occurrence]]:
    """Semaine des horaires de tous les lieux actifs d'un nœud (EF-PAROI-06)."""
    places = list(place_list(node=node))
    place_ids = [p.pk for p in places]
    schedules = MassSchedule.objects.filter(place_id__in=place_ids)
    exceptions = ScheduleException.objects.filter(place_id__in=place_ids)
    return places, compute_week(start=start, schedules=schedules, exceptions=exceptions, days=days)


def node_parent_ids(*, nodes: list[Node]) -> dict[str, str]:
    """{chemin du parent: id du parent} pour une liste de nœuds, en une requête (évite le N+1)."""
    parent_paths = {n.path[: -n.steplen] for n in nodes if n.depth > 1}
    return {path: str(pk) for path, pk in Node.objects.filter(path__in=parent_paths).values_list("path", "pk")}
