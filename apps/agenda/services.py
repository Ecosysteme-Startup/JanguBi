"""Événements et inscriptions de la V1 (SRS §3.5 EF-PAROI-07, lot L4).

Autorisation : ``evenements.gerer`` sur le nœud de l'événement ; portée globale réservée
à la plateforme. Annulation douce : un événement annulé garde ses inscriptions.
"""

import datetime
from functools import partial
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.agenda.models import Event, EventRegistration
from apps.core.exceptions import ApplicationError, ConflictError, PermissionDeniedError
from apps.hierarchy import authz
from apps.hierarchy.audit import audit_log
from apps.hierarchy.models import Node, PlaceOfWorship

UPDATABLE_FIELDS = ("title", "description", "event_type", "start_at", "end_at", "location", "max_participants")


def event_manage_check(*, user: Any, node: Node | None) -> None:
    if node is None:
        if not authz.peut(user, "plateforme.admin", None):
            raise PermissionDeniedError("Seule la plateforme crée des événements globaux.", code="global_scope_forbidden")
        return
    if not authz.peut(user, "evenements.gerer", node):
        raise PermissionDeniedError("Vous ne pouvez pas gérer les événements de ce nœud.", code="events_forbidden")


def _dates_check(*, start_at: datetime.datetime, end_at: datetime.datetime) -> None:
    if end_at <= start_at:
        raise ApplicationError("La fin doit suivre le début.", code="invalid_dates")


@transaction.atomic
def event_create(
    *,
    organizer: Any,
    title: str,
    start_at: datetime.datetime,
    end_at: datetime.datetime,
    node: Node | None = None,
    place: PlaceOfWorship | None = None,
    description: str = "",
    event_type: str = Event.EventType.OTHER,
    location: str = "",
    max_participants: int | None = None,
) -> Event:
    event_manage_check(user=organizer, node=node)
    _dates_check(start_at=start_at, end_at=end_at)
    if place is not None and (node is None or place.node_id != node.pk):
        raise ApplicationError("Le lieu de culte doit appartenir au nœud de l'événement.", code="place_not_in_node")
    event = Event.objects.create(
        organizer=organizer,
        title=title,
        description=description,
        event_type=event_type,
        start_at=start_at,
        end_at=end_at,
        location=location or (place.name if place else ""),
        max_participants=max_participants,
        scope_node=node,
        scope_place=place,
        scope_type=Event.ScopeType.GLOBAL if node is None else Event.ScopeType.PARISH,
    )
    audit_log(actor=organizer, action="evenement.creation", target=event, node=node)
    return event


@transaction.atomic
def event_update(*, event: Event, actor: Any, data: dict[str, Any]) -> Event:
    event_manage_check(user=actor, node=event.scope_node)
    unknown = set(data) - set(UPDATABLE_FIELDS)
    if unknown:
        raise ApplicationError("Champs non modifiables.", {"fields": sorted(unknown)}, code="field_not_updatable")
    if event.cancelled_at is not None:
        raise ApplicationError("Un événement annulé ne se modifie plus.", code="event_cancelled")
    _dates_check(start_at=data.get("start_at", event.start_at), end_at=data.get("end_at", event.end_at))
    if "max_participants" in data and data["max_participants"] is not None:
        registered = EventRegistration.objects.filter(event=event).count()
        if data["max_participants"] < registered:
            raise ApplicationError(
                f"Déjà {registered} inscrits : la jauge ne peut pas descendre en dessous.", code="capacity_below_registrations"
            )
    for field, value in data.items():
        setattr(event, field, value)
    if "start_at" in data:
        event.reminder_sent_at = None  # nouvelle date : nouveau rappel
    event.save()
    audit_log(actor=actor, action="evenement.modification", target=event, node=event.scope_node)
    return event


def _notify_cancellation(*, event: Event) -> None:
    """Chaque inscrit est prévenu par e-mail (modèle Email + tâche, jamais de SMTP direct)."""
    from apps.emails.models import Email
    from apps.emails.tasks import email_send as email_send_task

    subject = f"[Jàngu Bi] Événement annulé — {event.title}"
    html = (
        f"<p>Bonjour,</p><p>L'événement <strong>{event.title}</strong> prévu le "
        f"{timezone.localtime(event.start_at):%d/%m/%Y à %H:%M} a été annulé.</p>"
        "<p>Votre inscription est donc sans objet. Veuillez nous excuser pour ce contretemps.</p>"
    )
    emails = Email.objects.bulk_create(
        [
            Email(to=r.user.email, subject=subject, html=html, plain_text=html, status=Email.Status.SENDING)
            for r in event.registrations.select_related("user")
            if r.user.email
        ]
    )
    for email in emails:
        transaction.on_commit(partial(email_send_task.delay, email.id))


@transaction.atomic
def event_cancel(*, event: Event, actor: Any) -> Event:
    event_manage_check(user=actor, node=event.scope_node)
    if event.cancelled_at is not None:
        raise ApplicationError("Cet événement est déjà annulé.", code="event_cancelled")
    event.cancelled_at = timezone.now()
    event.cancelled_by = actor
    event.save(update_fields=["cancelled_at", "cancelled_by", "updated_at"])
    _notify_cancellation(event=event)
    audit_log(actor=actor, action="evenement.annulation", target=event, node=event.scope_node)
    return event


@transaction.atomic
def event_register(*, event: Event, user: Any) -> EventRegistration:
    """Inscription sous verrou de la ligne événement (sinon deux inscriptions concurrentes sur
    la dernière place passent toutes deux). Complet → 409. Idempotente pour la même personne."""
    locked = Event.objects.select_for_update().filter(pk=event.pk).first()
    if locked is None:
        raise ApplicationError("Événement introuvable.", code="not_found")
    if locked.cancelled_at is not None:
        raise ApplicationError("Cet événement a été annulé.", code="event_cancelled")
    if locked.end_at <= timezone.now():
        raise ApplicationError("Cet événement est terminé.", code="event_past")
    existing = EventRegistration.objects.filter(event=locked, user=user).first()
    if existing is not None:
        return existing
    if locked.max_participants is not None:
        if EventRegistration.objects.filter(event=locked).count() >= locked.max_participants:
            raise ConflictError("Cet événement est complet.", code="event_full")
    return EventRegistration.objects.create(event=locked, user=user)


@transaction.atomic
def event_unregister(*, event: Event, user: Any) -> None:
    deleted, _ = EventRegistration.objects.filter(event=event, user=user).delete()
    if not deleted:
        raise ApplicationError("Vous n'êtes pas inscrit à cet événement.", code="not_registered")


@transaction.atomic
def event_reminders_send(*, now: datetime.datetime | None = None) -> int:
    """Rappel la veille aux inscrits (EF-PAROI-08), une seule fois par événement."""
    from apps.messaging.services_notifications import people_notify

    now = now or timezone.now()
    due = Event.objects.select_for_update(skip_locked=True).filter(
        cancelled_at__isnull=True,
        reminder_sent_at__isnull=True,
        start_at__gt=now,
        start_at__lte=now + datetime.timedelta(hours=24),
    )
    count = 0
    for event in due:
        user_ids = list(event.registrations.values_list("user_id", flat=True))
        people_notify(
            user_ids=user_ids,
            topic="evenements",
            event_type="agenda.reminder",
            payload={"event_id": event.pk, "title": event.title, "start_at": event.start_at.isoformat()},
            email_template="evenement_rappel",
            email_context={
                "title": event.title,
                "start_at": timezone.localtime(event.start_at),
                "location": event.location,
                "event_id": event.pk,
            },
            now=now,
        )
        event.reminder_sent_at = now
        event.save(update_fields=["reminder_sent_at", "updated_at"])
        count += 1
    return count
