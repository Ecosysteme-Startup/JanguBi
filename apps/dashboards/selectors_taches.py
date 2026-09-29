"""Tâches du jour d'une paroisse (lot V1-routes, G01).

Agrégat en lecture seule : chaque rubrique n'apparaît que si la personne détient la capacité
correspondante sur la paroisse. Aucune donnée nominative sur les fidèles (les confessions du jour
donnent l'heure, le lieu, le confesseur et l'état du créneau, jamais le pénitent).
"""

import datetime
from typing import Any

from django.utils import timezone

from apps.hierarchy import authz
from apps.hierarchy.models import Node

TASK_CAPABILITIES = (
    "actes.traiter",
    "annonces.publier",
    "dons.saisir_quete",
    "dons.gerer_fonds",
    "confessions.gerer",
    "confessions.voir_planning",
    "intentions.gerer",
)


def _documents(node: Node) -> list[dict[str, Any]]:
    from apps.documents.models import DocumentRequest

    qs = DocumentRequest.objects.filter(target_node__path__startswith=node.path)
    S = DocumentRequest.Status
    return [
        {
            "code": "demandes_a_traiter",
            "label": "Demandes d'actes à traiter",
            "count": qs.filter(status__in=(S.SUBMITTED, S.UNDER_VERIFICATION)).count(),
        },
        {
            "code": "demandes_complement",
            "label": "Demandes en attente d'un complément",
            "count": qs.filter(status=S.INFO_REQUESTED).count(),
        },
    ]


def _collections(node: Node) -> list[dict[str, Any]]:
    from apps.donations.enums import CashCollectionStatus
    from apps.donations.models import CashCollection

    count = CashCollection.objects.filter(node=node, status=CashCollectionStatus.SAISIE).count()
    return [{"code": "quetes_a_confirmer", "label": "Quêtes à confirmer", "count": count}]


def _news(node: Node, day: datetime.date) -> list[dict[str, Any]]:
    from apps.news.models import Article
    from apps.news.selectors import next_sunday

    qs = Article.objects.filter(scope_node__path__startswith=node.path)
    return [
        {
            "code": "annonces_a_publier",
            "label": "Annonces en brouillon",
            "count": qs.filter(status=Article.Status.DRAFT).count(),
        },
        {
            "code": "annonces_du_dimanche",
            "label": "Annonces du dimanche à relire",
            "count": qs.filter(
                is_sunday_notice=True,
                sunday_date=next_sunday(today=day),
                status__in=(Article.Status.DRAFT, Article.Status.SCHEDULED),
            ).count(),
        },
    ]


def _intentions(node: Node, day: datetime.date) -> list[dict[str, Any]]:
    from apps.intentions.enums import IntentionStatus
    from apps.intentions.models import MassIntention

    qs = MassIntention.objects.filter(node=node)
    return [
        {
            "code": "intentions_a_planifier",
            "label": "Intentions de messe à planifier",
            "count": qs.filter(status=IntentionStatus.RECUE).count(),
        },
        {
            "code": "intentions_du_jour",
            "label": "Intentions de messe du jour",
            "count": qs.filter(status=IntentionStatus.PLANIFIEE, scheduled_date=day).count(),
        },
    ]


def _confessions(node: Node, day: datetime.date) -> list[dict[str, Any]]:
    from apps.confessions.models import ConfessionSlot
    from apps.hierarchy.persons import full_name

    tz = timezone.get_current_timezone()
    start = datetime.datetime.combine(day, datetime.time.min, tzinfo=tz)
    slots = (
        ConfessionSlot.objects.filter(
            place__node__path__startswith=node.path,
            starts_at__gte=start,
            starts_at__lt=start + datetime.timedelta(days=1),
        )
        .exclude(status=ConfessionSlot.Status.BLOQUE)
        .select_related("place", "priest__profile")
        .order_by("starts_at")
    )
    return [
        {
            "slot_id": s.pk,
            "starts_at": s.starts_at,
            "ends_at": s.ends_at,
            "place_name": s.place.name,
            "priest_name": full_name(s.priest) or "Prêtre",
            "reserved": s.status == ConfessionSlot.Status.RESERVE,
        }
        for s in slots
    ]


def today_tasks(*, user: Any, node: Node, day: datetime.date | None = None) -> dict[str, Any]:
    from apps.donations import access as dons_access

    day = day or timezone.localdate()
    tasks: list[dict[str, Any]] = []
    if authz.peut(user, "actes.traiter", node):
        tasks += _documents(node)
    if dons_access.parish_level(user, "dons.saisir_quete", node) or dons_access.parish_level(
        user, "dons.gerer_fonds", node
    ):
        tasks += _collections(node)
    if authz.peut(user, "annonces.publier", node):
        tasks += _news(node, day)
    if authz.peut(user, "intentions.gerer", node):
        tasks += _intentions(node, day)
    confessions = None
    if authz.peut(user, "confessions.gerer", node) or authz.peut(user, "confessions.voir_planning", node):
        confessions = _confessions(node, day)
        tasks.append(
            {
                "code": "confessions_du_jour",
                "label": "Créneaux de confession du jour",
                "count": len(confessions),
            }
        )
    return {"node": node, "date": day, "tasks": tasks, "confessions": confessions}
