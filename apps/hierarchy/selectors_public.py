"""Lectures de l'annuaire public : calculées en lot pour une page de nœuds (pas de N+1)."""

from collections import defaultdict
from datetime import date, time, timedelta
from typing import Any

from django.db.models import Q

from apps.hierarchy.enums import AssignmentStatus, EtatDeVie, ScheduleKind, StatutVerification, Weekday
from apps.hierarchy.models import MassSchedule, Node, OfficeAssignment, ScheduleException
from apps.hierarchy.week import compute_week


def next_sunday(*, today: date) -> date:
    """Le dimanche à venir, ou aujourd'hui si l'on est dimanche."""
    return today + timedelta(days=(Weekday.DIMANCHE - today.weekday()) % 7)


def nodes_lineage(*, nodes: list[Node]) -> dict[str, Node]:
    """{chemin: nœud} de tous les ancêtres des nœuds donnés, en une requête."""
    paths = {n.path[: n.steplen * i] for n in nodes for i in range(1, n.depth)}
    if not paths:
        return {}
    return {a.path: a for a in Node.objects.select_related("type").filter(path__in=paths)}


def nodes_sunday_masses(*, nodes: list[Node], sunday: date) -> dict[Any, list[time]]:
    """{id du nœud: heures des messes de ``sunday``} sur les lieux actifs, exceptions appliquées (2 requêtes)."""
    node_ids = [n.pk for n in nodes]
    if not node_ids:
        return {}
    scope = Q(place__node_id__in=node_ids, place__is_active=True, kind=ScheduleKind.MESSE)
    schedules = list(MassSchedule.objects.filter(scope, weekday=Weekday.DIMANCHE).select_related("place"))
    exceptions = list(ScheduleException.objects.filter(scope, date=sunday).select_related("place"))
    node_of_place = {s.place_id: s.place.node_id for s in schedules}
    node_of_place.update({e.place_id: e.place.node_id for e in exceptions})

    result: dict[Any, set[time]] = defaultdict(set)
    for occurrence in compute_week(start=sunday, schedules=schedules, exceptions=exceptions, days=1):
        result[node_of_place[occurrence.place_id]].add(occurrence.start_time)
    return {node_id: sorted(times) for node_id, times in result.items()}


def _display_name(person: Any) -> str:
    profile = getattr(person, "profile", None)
    return f"{getattr(profile, 'first_name', '')} {getattr(profile, 'last_name', '')}".strip()


def node_public_clergy(*, node: Node, today: date) -> list[dict[str, str]]:
    """Clercs vérifiés titulaires d'un office actif sur ce nœud : nom et office, rien d'autre.

    Une personne sans nom renseigné n'apparaît pas (son e-mail n'est jamais exposé)."""
    assignments = (
        OfficeAssignment.objects.filter(
            node=node,
            status=AssignmentStatus.ACTIVE,
            start_date__lte=today,
            person__is_active=True,
            person__etat_de_vie=EtatDeVie.CLERC,
            person__statut_verification=StatutVerification.VERIFIE,
        )
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=today))
        .select_related("person__profile", "office_type")
        .order_by("start_date", "pk")
    )
    clergy: list[dict[str, str]] = []
    for assignment in assignments:
        name = _display_name(assignment.person)
        if name:
            clergy.append({"name": name, "office": assignment.office_type.label})
    return clergy
