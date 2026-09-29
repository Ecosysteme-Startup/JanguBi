"""Lectures des intentions de messe (lot V1-routes)."""

import datetime
from typing import Any

from django.db.models import QuerySet

from apps.core.exceptions import NotFoundError, PermissionDeniedError
from apps.hierarchy import authz
from apps.hierarchy.models import Node
from apps.intentions.models import MassIntention

_RELATED = ("node", "place", "requester__profile")


def intentions_for_person(*, user: Any) -> QuerySet[MassIntention]:
    return MassIntention.objects.filter(requester=user).select_related(*_RELATED).order_by("-created_at")


def intention_get_for_person(*, user: Any, intention_id: Any) -> MassIntention:
    obj = intentions_for_person(user=user).filter(pk=intention_id).first()
    if obj is None:
        raise NotFoundError("Intention introuvable.")
    return obj


def intentions_for_parish(
    *,
    user: Any,
    node: Node,
    status: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> QuerySet[MassIntention]:
    if not authz.peut(user, "intentions.gerer", node):
        raise PermissionDeniedError("Vous ne gérez pas les intentions de cette paroisse.", code="intentions_forbidden")
    qs = MassIntention.objects.filter(node=node).select_related(*_RELATED)
    if status:
        qs = qs.filter(status=status)
    if date_from:
        qs = qs.filter(requested_date__gte=date_from)
    if date_to:
        qs = qs.filter(requested_date__lte=date_to)
    return qs.order_by("requested_date", "created_at")


def intention_get_for_staff(*, user: Any, intention_id: Any) -> MassIntention:
    """404 hors des paroisses gérées : on ne révèle pas l'existence d'une intention."""
    obj = MassIntention.objects.select_related(*_RELATED).filter(pk=intention_id).first()
    if obj is None or not authz.peut(user, "intentions.gerer", obj.node):
        raise NotFoundError("Intention introuvable.")
    return obj
