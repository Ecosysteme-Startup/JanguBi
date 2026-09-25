"""Tableaux de bord V1 (SRS §3.8 ; RG-09, RG-11).

Agrégats seulement : aucun nom, aucun e-mail, aucun contenu de message. Les requêtes de
messagerie ne lisent que des horodatages et des identifiants (``values_list``).
"""

import datetime
import statistics
from typing import Any

from django.core.cache import cache
from django.db.models import Count, Q
from django.utils import timezone

from apps.hierarchy.models import Node

PERIODS = (7, 30, 90, 365)
CACHE_SECONDS = 300
PLATFORM_CACHE_SECONDS = 60
NO_REPLY_HOURS = 48
BEAT_STALE_DAYS = 2


def _median_hours(deltas: list[datetime.timedelta]) -> float | None:
    if not deltas:
        return None
    return round(statistics.median(d.total_seconds() for d in deltas) / 3600, 1)


def _fideles(node: Node, since: datetime.datetime) -> dict[str, int]:
    from apps.users.models import BaseUser

    qs = BaseUser.objects.filter(paroisse_suivie__path__startswith=node.path, is_active=True)
    return qs.aggregate(
        attached=Count("pk"),
        active=Count("pk", filter=Q(last_seen_on__gte=since.date()) | Q(last_login__gte=since)),
        new=Count("pk", filter=Q(created_at__gte=since)),
    )


def _annonces(node: Node, since: datetime.datetime) -> dict[str, Any]:
    from apps.news.models import Article, ArticleRead

    published = Article.objects.filter(
        scope_node__path__startswith=node.path, status=Article.Status.PUBLISHED, published_at__gte=since
    )
    count = published.count()
    reads = ArticleRead.objects.filter(article__in=published).count()
    return {"published": count, "reads": reads, "reads_per_article": round(reads / count, 1) if count else None}


def _evenements(node: Node, since: datetime.datetime, now: datetime.datetime) -> dict[str, int]:
    from apps.agenda.models import Event, EventRegistration

    events = Event.objects.filter(scope_node__path__startswith=node.path, cancelled_at__isnull=True)
    return {
        "upcoming": events.filter(start_at__gte=now).count(),
        "registrations": EventRegistration.objects.filter(event__in=events, registered_at__gte=since).count(),
    }


def _actes(node: Node, since: datetime.datetime) -> dict[str, Any]:
    from apps.documents.models import DocumentRequest
    from apps.documents.selectors import overdue_ids, status_counts

    qs = DocumentRequest.objects.filter(target_node__path__startswith=node.path)
    closed = qs.filter(status="collected", closed_at__gte=since).values_list("created_at", "closed_at")
    return {
        **status_counts(queryset=qs),
        "received": qs.filter(created_at__gte=since).count(),
        "median_days_to_collect": _median_days(closed),
        "overdue": len(overdue_ids(qs)),
    }


def _median_days(rows: Any) -> float | None:
    days = [(end - start).days for start, end in rows if start and end]
    return statistics.median(days) if days else None


def _messagerie(node: Node, since: datetime.datetime, now: datetime.datetime) -> dict[str, Any]:
    """Conversations rattachées au sous-arbre par la paroisse suivie d'un participant.
    Calcul en SQL, une ligne par conversation : horodatage et auteur du premier message,
    horodatage de la première réponse d'un autre participant. Jamais le contenu."""
    from django.db.models import DurationField, ExpressionWrapper, F, OuterRef, Subquery

    from apps.messaging.models import Conversation, Message
    from apps.users.models import BaseUser

    followers = BaseUser.objects.filter(paroisse_suivie__path__startswith=node.path).values("pk")
    messages = Message.objects.filter(conversation=OuterRef("pk")).order_by("created_at")
    conversations = (
        Conversation.objects.filter(created_at__gte=since)
        .filter(Q(participant_a__in=followers) | Q(participant_b__in=followers))
        .annotate(
            first_at=Subquery(messages.values("created_at")[:1]),
            first_sender=Subquery(messages.values("sender_id")[:1]),
        )
        .annotate(
            reply_at=Subquery(
                Message.objects.filter(conversation=OuterRef("pk"))
                .exclude(sender_id=OuterRef("first_sender"))
                .order_by("created_at")
                .values("created_at")[:1]
            )
        )
    )
    totals = conversations.aggregate(
        total=Count("pk"),
        unanswered=Count(
            "pk",
            filter=Q(reply_at__isnull=True, first_at__lte=now - datetime.timedelta(hours=NO_REPLY_HOURS)),
        ),
    )
    delays = list(
        conversations.filter(reply_at__isnull=False)
        .annotate(delay=ExpressionWrapper(F("reply_at") - F("first_at"), output_field=DurationField()))
        .values_list("delay", flat=True)
    )
    return {
        "conversations": totals["total"],
        "median_first_reply_hours": _median_hours(delays),
        "unanswered_48h": totals["unanswered"],
    }


def _confessions(node: Node, since: datetime.datetime, now: datetime.datetime) -> dict[str, int]:
    from apps.confessions.models import ConfessionBooking, ConfessionSlot

    slots = ConfessionSlot.objects.filter(
        place__node__path__startswith=node.path, starts_at__gte=since, starts_at__lt=now
    )
    bookings = ConfessionBooking.objects.filter(slot__in=slots)
    by_status = dict(bookings.order_by().values_list("status").annotate(n=Count("pk")))
    return {
        "slots_offered": slots.count(),
        "booked": sum(by_status.values()),
        "honoured": by_status.get("honoree", 0),
        "absent": by_status.get("absent", 0),
        "cancelled": by_status.get("annulee_fidele", 0) + by_status.get("annulee_pretre", 0),
        "upcoming_booked": ConfessionBooking.objects.filter(
            slot__place__node__path__startswith=node.path, slot__starts_at__gte=now, status="reservee"
        ).count(),
    }


def node_dashboard(*, node: Node, period: int = 30, now: datetime.datetime | None = None) -> dict[str, Any]:
    """Indicateurs agrégés du sous-arbre de ``node`` (EF-DASH-01, -02). Mis en cache 5 minutes."""
    key = f"dashboards:node:{node.pk}:{period}"
    cached = cache.get(key) if now is None else None
    if cached is not None:
        return cached
    now = now or timezone.now()
    since = now - datetime.timedelta(days=period)
    data = {
        "node": {"id": str(node.pk), "name": node.name, "type": node.type.code},
        "period_days": period,
        "generated_at": now.isoformat(),
        "fideles": _fideles(node, since),
        "annonces": _annonces(node, since),
        "evenements": _evenements(node, since, now),
        "actes": _actes(node, since),
        "messagerie": _messagerie(node, since, now),
        "confessions": _confessions(node, since, now),
    }
    cache.set(key, data, CACHE_SECONDS)
    return data


def platform_dashboard(*, now: datetime.datetime | None = None) -> dict[str, Any]:
    """Plateforme (EF-DASH-03) : comptes, part du staff avec MFA, santé des files et de Beat.
    Mis en cache une minute (les retards d'actes parcourent toutes les demandes en cours)."""
    if now is None:
        cached = cache.get("dashboards:platform")
        if cached is not None:
            return cached
        data = _platform_dashboard(now=timezone.now())
        cache.set("dashboards:platform", data, PLATFORM_CACHE_SECONDS)
        return data
    return _platform_dashboard(now=now)


def _platform_dashboard(*, now: datetime.datetime) -> dict[str, Any]:
    from django_celery_beat.models import PeriodicTask

    from apps.documents.models import DocumentRequest
    from apps.documents.selectors import overdue_ids
    from apps.emails.models import Email
    from apps.hierarchy.enums import AssignmentStatus
    from apps.hierarchy.models import OfficeAssignment
    from apps.users.models import BaseUser

    month = now - datetime.timedelta(days=30)
    today = timezone.localdate(now)
    accounts = BaseUser.objects.filter(is_active=True).aggregate(
        total=Count("pk"),
        active_30d=Count("pk", filter=Q(last_seen_on__gte=month.date()) | Q(last_login__gte=month)),
        new_30d=Count("pk", filter=Q(created_at__gte=month)),
    )
    staff_ids = (
        OfficeAssignment.objects.filter(status=AssignmentStatus.ACTIVE, start_date__lte=today)
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=today))
        .values("person_id")
    )
    staff = BaseUser.objects.filter(pk__in=staff_ids, is_active=True).aggregate(
        total=Count("pk"), with_mfa_30d=Count("pk", filter=Q(last_mfa_on__gte=month.date()))
    )
    staff["mfa_share"] = round(staff["with_mfa_30d"] / staff["total"], 3) if staff["total"] else None
    tasks = [
        {
            "name": t.name,
            "task": t.task,
            "enabled": t.enabled,
            "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
            "stale": t.enabled
            and (t.last_run_at is None or now - t.last_run_at > datetime.timedelta(days=BEAT_STALE_DAYS)),
        }
        for t in PeriodicTask.objects.exclude(task__startswith="celery.").order_by("name")
    ]
    return {
        "generated_at": now.isoformat(),
        "accounts": accounts,
        "staff": staff,
        "health": {
            "emails_failed_7d": Email.objects.filter(
                status=Email.Status.FAILED, updated_at__gte=now - datetime.timedelta(days=7)
            ).count(),
            "document_requests_overdue": len(overdue_ids(DocumentRequest.objects.all(), now=now)),
            "beat_stale": sum(1 for t in tasks if t["stale"]),
        },
        "beat": tasks,
    }
