"""Équipe des compteurs de quête d'une paroisse (lot V1-routes, G08)."""

import datetime
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone

from apps.core.exceptions import NotFoundError
from apps.donations.models import CashCollection, CollectionCounter
from apps.hierarchy.models import Node

RECENT_DAYS = 90


def counters_for_parish(*, node: Node, include_inactive: bool = False) -> QuerySet[CollectionCounter]:
    qs = CollectionCounter.objects.filter(node=node)
    if not include_inactive:
        qs = qs.filter(is_active=True)
    return qs.order_by("name")


def counter_get(*, counter_id: Any) -> CollectionCounter:
    counter = CollectionCounter.objects.select_related("node__type").filter(pk=counter_id).first()
    if counter is None:
        raise NotFoundError("Compteur introuvable.")
    return counter


def counter_recent_names(*, node: Node, today: datetime.date | None = None) -> list[str]:
    """Noms déjà utilisés dans les quêtes des 90 derniers jours et absents de l'équipe :
    suggestions pour compléter l'équipe (ordre alphabétique, aucun classement)."""
    today = today or timezone.localdate()
    since = today - datetime.timedelta(days=RECENT_DAYS)
    rows = CashCollection.objects.filter(node=node, mass_date__gte=since).values_list("counter_one", "counter_two")
    team = {n.casefold() for n in counters_for_parish(node=node).values_list("name", flat=True)}
    names: dict[str, str] = {}
    for pair in rows:
        for name in pair:
            clean = (name or "").strip()
            if clean and clean.casefold() not in team:
                names.setdefault(clean.casefold(), clean)
    return sorted(names.values(), key=str.casefold)
