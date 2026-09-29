import structlog
from celery import shared_task
from django.utils import timezone

logger = structlog.get_logger(__name__)


@shared_task(bind=True, max_retries=3)
def purge_expired_conversations(self):
    from apps.messaging.models import Conversation
    from apps.messaging.services import conversation_purge_messages

    now = timezone.now()
    expired = Conversation.objects.filter(
        scheduled_purge_at__lt=now,
        scheduled_purge_at__isnull=False,
    )

    errors = []
    for conversation in expired:
        try:
            if not conversation.exports.filter(completed_at__isnull=False).exists():
                generate_conversation_export.delay(None, conversation_id=str(conversation.id))
            conversation_purge_messages(conversation=conversation)
        except Exception as exc:
            errors.append((str(conversation.id), str(exc)))
            logger.exception("conversation_purge_failed", conversation_id=str(conversation.id))

    if errors:
        raise self.retry(exc=Exception(f"Purge failed for {len(errors)} conversations"), countdown=3600)


@shared_task(bind=True, max_retries=3)
def notify_purge_upcoming(self):
    from datetime import timedelta

    from apps.messaging.models import Conversation
    from apps.messaging.services import notification_send

    warning_threshold = timezone.now() + timedelta(days=7)
    upcoming = Conversation.objects.filter(
        scheduled_purge_at__lte=warning_threshold,
        scheduled_purge_at__gt=timezone.now(),
    ).select_related("participant_a", "participant_b")

    for conversation in upcoming:
        payload = {
            "conversation_id": str(conversation.id),
            "purge_date": conversation.scheduled_purge_at.date().isoformat(),
        }
        for user in [conversation.participant_a, conversation.participant_b]:
            try:
                notification_send(
                    user=user,
                    event_type="conversation.purge_upcoming",
                    payload=payload,
                )
            except Exception:
                logger.exception(
                    "purge_notification_failed",
                    user_id=str(user.id),
                    conversation_id=str(conversation.id),
                )


@shared_task(bind=True, max_retries=3)
def generate_conversation_export(self, export_id, conversation_id=None):
    from apps.messaging.services import conversation_export_generate

    try:
        conversation_export_generate(export_id=export_id, conversation_id=conversation_id)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)


@shared_task(bind=True, max_retries=4, acks_late=True)
def push_deliver(self, *, device_ids, title, body, data, collapse_id=""):
    """Envoi push (file ``default``). Les erreurs passagères (429, 5xx, réseau) sont relancées
    pour les seuls appareils concernés ; un jeton refusé est désactivé, jamais relancé."""
    from apps.messaging.services_push import push_deliver_now

    result = push_deliver_now(device_ids=device_ids, title=title, body=body, data=data, collapse_id=collapse_id)
    if result["retry"] and self.request.retries < self.max_retries:
        self.retry(
            kwargs={"device_ids": result["retry"], "title": title, "body": body, "data": data, "collapse_id": collapse_id},
            countdown=60 * (2 ** self.request.retries),
            throw=False,
        )
    logger.info("push_delivered", sent=len(result["sent"]), invalid=len(result["invalid"]), retry=len(result["retry"]))
    return {k: len(v) for k, v in result.items()}
