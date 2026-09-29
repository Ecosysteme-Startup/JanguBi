"""Paroisses multiples (décisions 6-8) : lectures des appartenances."""

from typing import Any

from django.db.models import Q, QuerySet

from apps.hierarchy.models import Node, ParishMembership


def memberships_of(*, user: Any) -> list[ParishMembership]:
    """Appartenances actives du fidèle, la principale d'abord. Un ``paroisse_suivie`` écrit hors
    des services (sans ligne d'appartenance) compte comme principale."""
    rows = list(
        ParishMembership.objects.filter(user=user, removed_by_parish_at__isnull=True)
        .select_related("node", "node__type")
        .order_by("-is_primary", "joined_at")
    )
    legacy_id = getattr(user, "paroisse_suivie_id", None)
    if legacy_id and not any(m.node_id == legacy_id for m in rows):
        if not ParishMembership.objects.filter(user=user, node_id=legacy_id).exists():
            node = Node.objects.select_related("type").filter(pk=legacy_id).first()
            if node is not None:
                legacy = ParishMembership(
                    user=user,
                    node=node,
                    is_primary=not any(m.is_primary for m in rows),
                    joined_at=user.created_at,
                )
                rows.insert(0, legacy)
    return rows


def member_node_paths(*, user: Any) -> list[str]:
    """Chemins des paroisses dont ``user`` est membre (principale ou secondaire)."""
    paths = list(
        ParishMembership.objects.filter(user=user, removed_by_parish_at__isnull=True).values_list(
            "node__path", flat=True
        )
    )
    followed = getattr(user, "paroisse_suivie", None)
    if followed is not None and followed.path not in paths:
        if not ParishMembership.objects.filter(user=user, node=followed, removed_by_parish_at__isnull=False).exists():
            paths.insert(0, followed.path)
    return paths


def secondary_parishes(*, user: Any) -> list[Node]:
    return [m.node for m in memberships_of(user=user) if not m.is_primary]


def is_parish_member(*, user: Any, node: Node) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return any(node.path == p for p in member_node_paths(user=user))


def members_of(*, node: Node, include_removed: bool = False, q: str = "") -> QuerySet[ParishMembership]:
    """Membres d'une paroisse (côté paroisse, ``paroissiens.gerer``), les plus récents d'abord."""
    qs = ParishMembership.objects.filter(node=node).select_related("user", "user__profile", "removed_by__profile")
    if not include_removed:
        qs = qs.filter(removed_by_parish_at__isnull=True)
    if q := q.strip():
        qs = qs.filter(
            Q(user__email__icontains=q) | Q(user__profile__first_name__icontains=q) | Q(user__profile__last_name__icontains=q)
        )
    return qs.order_by("-joined_at")
