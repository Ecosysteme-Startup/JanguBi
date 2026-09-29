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


_PLANNED = ("planifiee", "celebree")


def _mass_label(start: datetime.time) -> str:
    return f"Messe de {start.hour} h {start.minute:02d}" if start.minute else f"Messe de {start.hour} h"


def parish_masses_of_day(*, user: Any, node: Node, day: datetime.date) -> dict[str, Any]:
    """Messes d'un jour (horaires et exceptions des lieux actifs) avec intentions retenues et plafond."""
    from apps.hierarchy.selectors import node_week
    from apps.intentions.services import max_per_mass

    if not authz.peut(user, "intentions.gerer", node):
        raise PermissionDeniedError("Vous ne gérez pas les intentions de cette paroisse.", code="intentions_forbidden")
    places, occurrences = node_week(node=node, start=day, days=1)
    names = {p.pk: p.name for p in places}
    cap = max_per_mass(node=node)
    planned = list(
        MassIntention.objects.filter(node=node, scheduled_date=day, status__in=_PLANNED).values_list(
            "place_id", "scheduled_time"
        )
    )
    masses = []
    for occ in sorted((o for o in occurrences if o.kind == "messe"), key=lambda o: (o.start_time, o.place_id)):
        count = sum(1 for pid, t in planned if pid == occ.place_id and t == occ.start_time)
        masses.append(
            {
                "place_id": occ.place_id,
                "place_name": names.get(occ.place_id, ""),
                "start_time": occ.start_time,
                "label": _mass_label(occ.start_time),
                "language": occ.language,
                "note": occ.note,
                "intentions_count": count,
                "max_intentions": cap,
                "remaining": max(cap - count, 0),
                "is_full": count >= cap,
            }
        )
    return {
        "node": {"id": str(node.pk), "name": node.name},
        "date": day,
        "max_per_mass": cap,
        "masses": masses,
        "without_time_count": sum(1 for _, t in planned if t is None),
    }


def parish_sheet(*, user: Any, node: Node, day: datetime.date) -> dict[str, Any]:
    """Feuille imprimable : intentions retenues pour le jour, groupées par messe. Jamais de montant."""
    from apps.intentions.serializers import StaffMassIntentionOutputSerializer

    data = parish_masses_of_day(user=user, node=node, day=day)
    rows = list(
        MassIntention.objects.filter(node=node, scheduled_date=day, status__in=_PLANNED)
        .select_related(*_RELATED)
        .order_by("created_at")
    )
    announce = StaffMassIntentionOutputSerializer().get_announced_as

    def line(obj: MassIntention) -> dict[str, Any]:
        return {"id": str(obj.pk), "kind": obj.kind, "kind_label": obj.get_kind_display(),
                "intention": obj.intention, "announced_as": announce(obj), "status": obj.status}

    used: set[Any] = set()
    groups = []
    for mass in data["masses"]:
        items = [r for r in rows if r.place_id == mass["place_id"] and r.scheduled_time == mass["start_time"]]
        used.update(r.pk for r in items)
        groups.append({**mass, "intentions": [line(r) for r in items]})
    others = [r for r in rows if r.pk not in used]
    return {
        "node": data["node"],
        "date": day,
        "masses": groups,
        # Retenues ce jour sans messe reconnue (heure libre ou horaire modifié depuis).
        "other_intentions": [{**line(r), "scheduled_mass": r.scheduled_mass} for r in others],
    }
