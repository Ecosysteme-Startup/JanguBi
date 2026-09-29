"""Envoi des notifications push (plan V2 §4, lot B2).

- ``push_send(user, *, title, body, data)`` : API interne pour tout module ; l'envoi part
  dans une tâche Celery après la transaction (file ``default``).
- ``push_for_notification(...)`` : branchée sur la création d'une ``Notification``
  (``notification_send``, ``people_notify``) ; respecte la préférence ``push`` et la plage
  de silence (envoi différé à la fin du silence).
- Aucun contenu sensible sur l'écran verrouillé : ni extrait de message, ni motif d'un
  rendez-vous, ni nature d'une demande. Seulement « Nouveau message du Père … » ou une phrase
  générique ; les données ne portent que des identifiants.
"""

import datetime
import logging
from functools import partial
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.hierarchy.enums import DegreOrdre
from apps.messaging.models import NotificationPreference, PushDevice
from apps.messaging.push_providers import ApnsProvider, FcmProvider, PushMessage, PushOutcome, provider_for
from apps.messaging.quiet_hours import quiet_until

logger = logging.getLogger(__name__)

PUSH_TITLE = "Jàngu Bi"
GENERIC_BODY = "Vous avez une nouvelle notification."
# Phrases neutres par type d'événement : rien qui trahisse une pratique religieuse ou une démarche.
EVENT_BODIES: dict[str, str] = {
    "conversation.purge_upcoming": "Un de vos échanges arrive à sa date d'effacement.",
    "confessions.reminder": "Rappel : vous avez un rendez-vous prochainement.",
    "confessions.cancelled": "Un de vos rendez-vous a été modifié.",
    "documents.status": "Votre demande a avancé.",
    "documents.assigned": "Une demande vous a été confiée.",
    "agenda.reminder": "Rappel d'un événement de votre paroisse.",
    "news.published": "Nouvelle annonce de votre paroisse.",
    "personnes.complement": "Votre profil demande votre attention.",
    "personnes.complement_fourni": "Un profil a été complété.",
}
_ORDER_PREFIX: dict[str, str] = {
    DegreOrdre.PRETRE: "du Père ",
    DegreOrdre.EVEQUE: "de Mgr ",
    DegreOrdre.DIACRE_PERMANENT: "du diacre ",
    DegreOrdre.DIACRE_TRANSITOIRE: "du diacre ",
}


# --- Contenu ---------------------------------------------------------------------------------


def _sender_label(sender_id: Any) -> str:
    from apps.users.models import BaseUser

    sender = BaseUser.objects.select_related("profile").filter(pk=sender_id).first() if sender_id else None
    if sender is None:
        return ""
    profile = getattr(sender, "profile", None)
    name = f"{getattr(profile, 'first_name', '')} {getattr(profile, 'last_name', '')}".strip()
    if not name:
        return ""
    return f"{_ORDER_PREFIX.get(sender.degre_ordre, 'de ')}{name}"


def push_content(*, event_type: str, payload: dict[str, Any]) -> tuple[str, str]:
    """Titre et texte affichés. Jamais d'extrait du contenu (messages chiffrés au repos)."""
    if event_type == "new_message":
        label = _sender_label(payload.get("sender_id"))
        return PUSH_TITLE, f"Nouveau message {label}" if label else "Vous avez un nouveau message."
    return PUSH_TITLE, EVENT_BODIES.get(event_type, GENERIC_BODY)


def push_data(*, event_type: str, payload: dict[str, Any], notification_id: Any = None) -> dict[str, str]:
    """Données de routage de l'app : type d'événement et identifiants seulement (chaînes, exigé par FCM)."""
    data = {"event_type": event_type}
    if notification_id is not None:
        data["notification_id"] = str(notification_id)
    for key, value in payload.items():
        if key.endswith("_id") and value is not None and key != "sender_id":
            data[key] = str(value)
    return data


# --- Envoi -----------------------------------------------------------------------------------


def _active_devices(user_id: Any) -> list[int]:
    return list(PushDevice.objects.filter(user_id=user_id, disabled_at__isnull=True).values_list("pk", flat=True))


def push_send(
    *,
    user: Any,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    collapse_id: str = "",
    eta: datetime.datetime | None = None,
) -> int:
    """Programme l'envoi vers les appareils actifs de ``user`` (après la transaction).
    Renvoie le nombre d'appareils visés (0 si le push est coupé ou sans appareil)."""
    if not settings.PUSH_ENABLED:
        return 0
    device_ids = _active_devices(getattr(user, "pk", user))
    if not device_ids:
        return 0
    from apps.messaging.tasks import push_deliver

    kwargs = {
        "device_ids": device_ids,
        "title": title,
        "body": body,
        "data": {k: str(v) for k, v in (data or {}).items()},
        "collapse_id": collapse_id,
    }
    if eta is None:
        transaction.on_commit(partial(push_deliver.apply_async, kwargs=kwargs))
    else:
        transaction.on_commit(partial(push_deliver.apply_async, kwargs=kwargs, eta=eta))
    return len(device_ids)


def push_for_notification(
    *,
    user_id: Any,
    event_type: str,
    payload: dict[str, Any],
    notification_id: Any = None,
    preference: NotificationPreference | None = None,
    now: datetime.datetime | None = None,
) -> int:
    """Push qui accompagne une notification, selon la préférence ``push`` et la plage de silence."""
    if not settings.PUSH_ENABLED:
        return 0
    pref = preference or NotificationPreference.objects.filter(user_id=user_id).first() or NotificationPreference()
    if not pref.push:
        return 0
    now = timezone.localtime(now or timezone.now())
    eta = quiet_until(now=now, start=pref.quiet_start, end=pref.quiet_end)
    title, body = push_content(event_type=event_type, payload=payload)
    return push_send(
        user=user_id,
        title=title,
        body=body,
        data=push_data(event_type=event_type, payload=payload, notification_id=notification_id),
        collapse_id=str(notification_id or ""),
        eta=eta,
    )


def push_deliver_now(
    *, device_ids: list[int], title: str, body: str, data: dict[str, str], collapse_id: str = ""
) -> dict[str, list[int]]:
    """Envoie à chaque appareil et désactive les jetons refusés. Renvoie les appareils
    ``sent``, ``invalid`` et ``retry`` (erreurs passagères, à relancer par la tâche)."""
    fcm, apns = FcmProvider.from_settings(), ApnsProvider.from_settings()
    message = PushMessage(title=title, body=body, data=data, collapse_id=collapse_id)
    result: dict[str, list[int]] = {"sent": [], "invalid": [], "retry": [], "skipped": []}
    devices = PushDevice.objects.filter(pk__in=device_ids, disabled_at__isnull=True)
    for device in devices:
        provider = provider_for(platform=device.platform, token=device.token, fcm=fcm, apns=apns)
        if provider is None:
            result["skipped"].append(device.pk)
            continue
        outcome: PushOutcome = provider.send(token=device.token, message=message)
        if outcome.ok:
            result["sent"].append(device.pk)
        elif outcome.invalid_token:
            result["invalid"].append(device.pk)
        elif outcome.retryable:
            result["retry"].append(device.pk)
        else:
            result["skipped"].append(device.pk)
            logger.warning("push.rejected", extra={"device_id": device.pk, "detail": outcome.detail})
    if result["invalid"]:
        push_devices_disable(device_ids=result["invalid"])
    return result


@transaction.atomic
def push_devices_disable(*, device_ids: list[int]) -> int:
    return PushDevice.objects.filter(pk__in=device_ids, disabled_at__isnull=True).update(
        disabled_at=timezone.now(), updated_at=timezone.now()
    )
