"""Diffusion de notifications selon les préférences de chacun (EF-PAROI-08)."""

import datetime
import logging
from collections.abc import Iterable
from functools import partial
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone

from apps.messaging.models import Notification, NotificationPreference
from apps.messaging.quiet_hours import quiet_until
from apps.messaging.services_push import push_for_notification

logger = logging.getLogger(__name__)

TOPICS = {"annonces": "topic_annonces", "evenements": "topic_evenements"}
PREFERENCE_FIELDS = ("in_app", "email", "push", "topic_annonces", "topic_evenements", "quiet_start", "quiet_end")


def preferences_get(*, user: Any) -> NotificationPreference:
    """Préférences de la personne (non enregistrées tant qu'elle ne les modifie pas)."""
    return NotificationPreference.objects.filter(user=user).first() or NotificationPreference(user=user)


@transaction.atomic
def preferences_update(*, user: Any, data: dict[str, Any]) -> NotificationPreference:
    preference, _ = NotificationPreference.objects.get_or_create(user=user)
    for field in PREFERENCE_FIELDS:
        if field in data:
            setattr(preference, field, data[field])
    preference.save()
    return preference


def _preferences_for(user_ids: list[Any]) -> dict[Any, NotificationPreference]:
    return {p.user_id: p for p in NotificationPreference.objects.filter(user_id__in=user_ids)}


def _ws_push(user_id: Any, event_type: str, payload: dict[str, Any]) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(f"user_{user_id}", {"type": "notification.push", "event_type": event_type, **payload})
    except Exception:  # noqa: BLE001 — une socket fermée ne doit pas bloquer la diffusion
        logger.warning("notification.ws_push_failed", extra={"user_id": str(user_id)})


def _email_queue(*, to: str, template: str, context: dict[str, Any], eta: datetime.datetime | None) -> None:
    from apps.emails.services import email_queue

    email_queue(to=to, template=f"notifications/{template}", context=context, eta=eta)


@transaction.atomic
def people_notify(
    *,
    user_ids: Iterable[Any],
    topic: str | None,
    event_type: str,
    payload: dict[str, Any],
    email_template: str | None = None,
    email_context: dict[str, Any] | None = None,
    now: datetime.datetime | None = None,
) -> int:
    """Notification in-app immédiate (sans bruit : elle attend dans la liste) et e-mail hors
    plage de silence, sinon différé à la fin du silence. Renvoie le nombre de personnes notifiées.

    ``topic=None`` : notification personnelle (rendez-vous, demande) envoyée quelle que soit
    la préférence par thème ; les canaux (in-app, e-mail) et la plage de silence s'appliquent."""
    from apps.users.models import BaseUser

    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return 0
    now = timezone.localtime(now or timezone.now())
    preferences = _preferences_for(ids)
    topic_field = TOPICS[topic] if topic is not None else None
    notifications = []
    pushes: list[tuple[Any, NotificationPreference]] = []
    emails: list[tuple[str, datetime.datetime | None]] = []
    for user in BaseUser.objects.filter(pk__in=ids, is_active=True).only("pk", "email"):
        pref = preferences.get(user.pk) or NotificationPreference(user_id=user.pk)
        if topic_field is not None and not getattr(pref, topic_field):
            continue
        if pref.in_app:
            notifications.append(Notification(user_id=user.pk, event_type=event_type, payload=payload))
        if pref.push:
            pushes.append((user.pk, pref))
        if pref.email and email_template and user.email:
            emails.append((user.email, quiet_until(now=now, start=pref.quiet_start, end=pref.quiet_end)))

    Notification.objects.bulk_create(notifications, batch_size=500)
    for notification in notifications:
        transaction.on_commit(partial(_ws_push, notification.user_id, event_type, payload))
    by_user = {n.user_id: n.pk for n in notifications}
    for user_id, pref in pushes:
        push_for_notification(
            user_id=user_id,
            event_type=event_type,
            payload=payload,
            notification_id=by_user.get(user_id),
            preference=pref,
            now=now,
        )
    for to, eta in emails:
        _email_queue(to=to, template=email_template or "", context=email_context or {}, eta=eta)
    return len({n.user_id for n in notifications} | {to for to, _ in emails})
