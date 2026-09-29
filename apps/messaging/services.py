from datetime import date, timedelta
from typing import TYPE_CHECKING, Optional

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import ApplicationError
from apps.files.models import File
from apps.messaging.models import (
    Conversation,
    ConversationExport,
    Message,
    MessageBlock,
    MessageReaction,
    MessagingAvailability,
    MessagingCguAcceptance,
    Notification,
)
from apps.users.models import BaseUser

if TYPE_CHECKING:  # annotations seules ; l'import runtime reste local (anti-circulaire)
    from apps.messaging.models import PushDevice

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_participants(a: BaseUser, b: BaseUser) -> tuple[BaseUser, BaseUser]:
    if str(a.id) < str(b.id):
        return a, b
    return b, a


def _check_not_blocked(sender: BaseUser, receiver: BaseUser) -> None:
    if MessageBlock.objects.filter(
        blocker__in=[sender, receiver],
        blocked__in=[sender, receiver],
    ).exists():
        raise ApplicationError("Échange bloqué entre ces deux utilisateurs.")


def _user_display_name(user: BaseUser) -> str:
    profile = getattr(user, "profile", None)
    if profile:
        return f"{profile.first_name} {profile.last_name}".strip() or user.email
    return user.email


def _check_cgu(conversation: Conversation, user: BaseUser) -> None:
    # Acceptation globale (par utilisateur) : vaut pour toutes les conversations.
    if MessagingCguAcceptance.objects.filter(user=user).exists():
        return
    # Compat : flags historiques par conversation.
    if user.id == conversation.participant_a_id:
        if conversation.cgu_accepted_by_a is None:
            raise ApplicationError("Vous devez accepter les CGU de messagerie.")
    else:
        if conversation.cgu_accepted_by_b is None:
            raise ApplicationError("Vous devez accepter les CGU de messagerie.")


def _check_rate_limit(sender: BaseUser, conversation: Conversation) -> None:
    key = f"msg_rate:{conversation.id}:{sender.id}:{date.today()}"
    count = cache.get_or_set(key, 0, timeout=86400)
    if count >= settings.MESSAGING_RATE_LIMIT_PER_DAY:
        raise ApplicationError(
            f"Limite de {settings.MESSAGING_RATE_LIMIT_PER_DAY} messages par jour atteinte."
        )
    cache.incr(key)


def _fanout_ws(conversation: Conversation, event_type: str, payload: dict) -> None:
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        f"conv_{conversation.id}",
        {"type": event_type, **payload},
    )


def _fanout_notification(user: BaseUser, event_type: str, payload: dict) -> None:
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        f"user_{user.id}",
        {"type": "notification.push", "event_type": event_type, **payload},
    )


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------


CONFESSION_NOTICE = (
    "La confession ne peut pas se faire par message. Pour recevoir le sacrement de réconciliation, "
    "prenez rendez-vous avec un prêtre : la confession se vit en présence du prêtre."
)
ADULT_AGE = 18
MINOR_MESSAGE = (
    "La messagerie avec un prêtre est réservée aux personnes majeures. Si tu as moins de 18 ans, "
    "parle à un prêtre de ta paroisse avec tes parents ou ton catéchiste, ou prends rendez-vous à l'accueil."
)


def age_on(*, birth: date, on: date) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def adult_check(*, user: BaseUser) -> None:
    """RG-13 : messagerie réservée aux majeurs en V1 (date de naissance du profil obligatoire)."""
    from apps.core.exceptions import PermissionDeniedError

    birth = getattr(getattr(user, "profile", None), "date_of_birth", None)
    if birth is None:
        raise PermissionDeniedError(
            "Renseignez votre date de naissance dans votre profil pour écrire à un prêtre.", code="birth_date_required"
        )
    if age_on(birth=birth, on=timezone.localdate()) < ADULT_AGE:
        raise PermissionDeniedError(MINOR_MESSAGE, code="minor")


def reachable_check(*, priest: BaseUser) -> None:
    """EF-PRE-01 : seul un titulaire de ``messagerie.recevoir_fideles`` qui accepte de nouveaux
    échanges peut être contacté (plus de contact d'un utilisateur quelconque par UUID)."""
    from apps.hierarchy import authz

    if not authz.a_la_capacite(priest, "messagerie.recevoir_fideles"):
        raise ApplicationError("Ce prêtre n'est pas joignable par la messagerie.", code="not_reachable")
    availability = MessagingAvailability.objects.filter(user=priest).first()
    if availability is not None and not availability.accepts_new_conversations:
        raise ApplicationError("Ce prêtre ne prend pas de nouveaux échanges pour le moment.", code="not_accepting")


@transaction.atomic
def conversation_get_or_create(
    *, fidele: BaseUser, priest: BaseUser
) -> tuple[Conversation, bool]:
    existing = Conversation.objects.filter(
        participant_a=min(fidele, priest, key=lambda u: str(u.id)),
        participant_b=max(fidele, priest, key=lambda u: str(u.id)),
    ).first()
    if existing is not None:
        return existing, False
    if fidele.pk == priest.pk:
        raise ApplicationError("Conversation impossible avec soi-même.", code="self_conversation")
    reachable_check(priest=priest)
    adult_check(user=fidele)
    _check_not_blocked(fidele, priest)
    participant_a, participant_b = _normalize_participants(fidele, priest)
    conversation, created = Conversation.objects.get_or_create(
        participant_a=participant_a,
        participant_b=participant_b,
    )
    return conversation, created


@transaction.atomic
def conversation_open_by_priest(*, priest: BaseUser, fidele: BaseUser) -> tuple[Conversation, bool]:
    """Le prêtre (titulaire de ``messagerie.recevoir_fideles``) écrit le premier à un fidèle,
    par exemple depuis une demande d'acte (lot V1-routes, G03). Sa propre disponibilité ne
    l'empêche pas d'écrire ; le fidèle doit être majeur (RG-13) et aucun blocage ne doit exister."""
    from apps.hierarchy import authz

    if fidele.pk == priest.pk:
        raise ApplicationError("Conversation impossible avec soi-même.", code="self_conversation")
    if not authz.a_la_capacite(priest, "messagerie.recevoir_fideles"):
        raise ApplicationError("Vous n'êtes pas joignable par la messagerie.", code="not_reachable")
    participant_a, participant_b = _normalize_participants(fidele, priest)
    existing = Conversation.objects.filter(participant_a=participant_a, participant_b=participant_b).first()
    if existing is not None:
        return existing, False
    adult_check(user=fidele)
    _check_not_blocked(priest, fidele)
    return Conversation.objects.get_or_create(participant_a=participant_a, participant_b=participant_b)


@transaction.atomic
def availability_update(*, user: BaseUser, data: dict) -> MessagingAvailability:
    """EF-PRE-07 : disponibilités d'un prêtre joignable."""
    from apps.hierarchy import authz

    if not authz.a_la_capacite(user, "messagerie.recevoir_fideles"):
        from apps.core.exceptions import PermissionDeniedError

        raise PermissionDeniedError("Réservé aux prêtres joignables.", code="not_reachable")
    availability, _ = MessagingAvailability.objects.select_for_update().get_or_create(user=user)
    fields = [f for f in ("accepts_new_conversations", "absent_until", "reply_windows", "note") if f in data]
    for field in fields:
        setattr(availability, field, data[field])
    availability.save(update_fields=[*fields, "updated_at"])
    return availability


@transaction.atomic
def messaging_cgu_accept(*, user: BaseUser) -> MessagingCguAcceptance:
    """
    Acceptation GLOBALE des CGU de messagerie — une fois pour toutes les
    conversations. Idempotent : ré-accepter ne lève pas d'erreur.
    """
    acceptance, _created = MessagingCguAcceptance.objects.get_or_create(
        user=user,
        defaults={"accepted_at": timezone.now()},
    )
    return acceptance


@transaction.atomic
def conversation_accept_cgu(*, conversation: Conversation, user: BaseUser) -> Conversation:
    now = timezone.now()
    if user.id == conversation.participant_a_id:
        if conversation.cgu_accepted_by_a is not None:
            raise ApplicationError("CGU déjà acceptées.")
        conversation.cgu_accepted_by_a = now
        conversation.save(update_fields=["cgu_accepted_by_a", "updated_at"])
    else:
        if conversation.cgu_accepted_by_b is not None:
            raise ApplicationError("CGU déjà acceptées.")
        conversation.cgu_accepted_by_b = now
        conversation.save(update_fields=["cgu_accepted_by_b", "updated_at"])
    return conversation


@transaction.atomic
def conversation_archive(*, conversation: Conversation, user: BaseUser) -> Conversation:
    conversation.is_archived = True
    conversation.save(update_fields=["is_archived", "updated_at"])
    return conversation


@transaction.atomic
def conversation_delete(*, conversation: Conversation, user: BaseUser) -> Conversation:
    Message.objects.filter(conversation=conversation).update(
        content="",
        deleted_at=timezone.now(),
    )
    purge_at = timezone.now() + timedelta(days=30)
    conversation.scheduled_purge_at = purge_at
    conversation.save(update_fields=["scheduled_purge_at", "updated_at"])
    return conversation


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


@transaction.atomic
def message_send(
    *,
    conversation: Conversation,
    sender: BaseUser,
    content: str,
    client_message_id: Optional[str] = None,
    reply_to: Optional[Message] = None,
) -> Message:
    receiver = (
        conversation.participant_b
        if sender.id == conversation.participant_a_id
        else conversation.participant_a
    )

    _check_not_blocked(sender, receiver)
    _check_cgu(conversation, sender)
    _check_rate_limit(sender, conversation)
    # RG-13 : le côté fidèle doit être majeur, y compris dans une conversation ouverte avant la V1.
    from apps.hierarchy import authz

    if not authz.a_la_capacite(sender, "messagerie.recevoir_fideles"):
        adult_check(user=sender)

    if client_message_id:
        existing = Message.objects.filter(client_message_id=client_message_id).first()
        if existing:
            return existing

    now = timezone.now()
    message = Message.objects.create(
        conversation=conversation,
        sender=sender,
        content=content,
        reply_to=reply_to,
        client_message_id=client_message_id,
    )

    purge_days = settings.MESSAGING_PURGE_DAYS
    Conversation.objects.filter(pk=conversation.pk).update(
        last_message_at=now,
        scheduled_purge_at=now + timedelta(days=purge_days),
    )

    transaction.on_commit(
        lambda: _fanout_ws(
            conversation,
            "conv_message",
            {
                "message": {
                    "id": str(message.id),
                    "sender_id": str(sender.id),
                    "sender_name": None,
                    "content": content,
                    "content_type": "text",
                    "client_message_id": str(client_message_id) if client_message_id else None,
                    "reply_to_id": str(reply_to.id) if reply_to else None,
                    "read_at": None,
                    "deleted_at": None,
                    "is_deleted": False,
                    "reactions": [],
                    "attachments": [],
                    "created_at": now.isoformat(),
                }
            },
        )
    )

    # Persist a Notification row so the recipient sees it even when offline.
    # Le payload porte le nom de l'expéditeur pour permettre un rendu direct
    # (toast, ligne de liste) sans refetch — mais PAS d'extrait du contenu :
    # les messages sont chiffrés au repos (Fernet) et Notification.payload est
    # un JSONField en clair.
    transaction.on_commit(
        lambda: notification_send(
            user=receiver,
            event_type="new_message",
            payload={
                "conversation_id": str(conversation.id),
                "sender_id": str(sender.id),
                "sender_name": _user_display_name(sender),
                "sent_at": now.isoformat(),
            },
        )
    )

    return message


@transaction.atomic
def message_mark_read(*, conversation: Conversation, reader: BaseUser) -> int:
    updated = (
        Message.objects.filter(
            conversation=conversation,
            read_at__isnull=True,
            deleted_at__isnull=True,
        )
        .exclude(sender=reader)
        .update(read_at=timezone.now())
    )

    if updated:
        transaction.on_commit(
            lambda: _fanout_ws(
                conversation,
                "conv_read",
                {"reader_id": str(reader.id)},
            )
        )

    return updated


@transaction.atomic
def message_delete(*, message: Message, user: BaseUser) -> Message:
    if message.sender_id != user.id:
        raise ApplicationError("Vous ne pouvez supprimer que vos propres messages.")
    if message.is_deleted:
        raise ApplicationError("Message déjà supprimé.")
    message.content = ""
    message.deleted_at = timezone.now()
    message.save(update_fields=["content", "deleted_at", "updated_at"])
    return message


@transaction.atomic
def message_react(*, message: Message, user: BaseUser, emoji: str) -> MessageReaction:
    reaction, _ = MessageReaction.objects.get_or_create(
        message=message,
        user=user,
        emoji=emoji,
    )
    return reaction


@transaction.atomic
def message_unreact(*, message: Message, user: BaseUser, emoji: str) -> None:
    MessageReaction.objects.filter(message=message, user=user, emoji=emoji).delete()


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


@transaction.atomic
def block_user(*, blocker: BaseUser, blocked: BaseUser) -> MessageBlock:
    if blocker.id == blocked.id:
        raise ApplicationError("Impossible de se bloquer soi-même.")
    block, created = MessageBlock.objects.get_or_create(blocker=blocker, blocked=blocked)
    if not created:
        raise ApplicationError("Cet utilisateur est déjà bloqué.")
    return block


@transaction.atomic
def unblock_user(*, blocker: BaseUser, blocked: BaseUser) -> None:
    deleted, _ = MessageBlock.objects.filter(blocker=blocker, blocked=blocked).delete()
    if not deleted:
        raise ApplicationError("Aucun blocage trouvé.")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@transaction.atomic
def conversation_export_request(
    *, conversation: Conversation, user: BaseUser
) -> ConversationExport:
    export = ConversationExport.objects.create(
        conversation=conversation,
        requested_by=user,
    )

    def _launch_task():
        from apps.messaging.tasks import generate_conversation_export

        generate_conversation_export.delay(export.id)

    transaction.on_commit(_launch_task)
    return export


# ---------------------------------------------------------------------------
# Notifications (REQ-RT)
# ---------------------------------------------------------------------------


@transaction.atomic
def notification_send(
    *, user: BaseUser, event_type: str, payload: dict
) -> Notification:
    from apps.messaging.services_push import push_for_notification

    notification = Notification.objects.create(
        user=user,
        event_type=event_type,
        payload=payload,
    )

    transaction.on_commit(lambda: _fanout_notification(user, event_type, payload))
    # Push hors de l'app (préférence « push » et plage de silence respectées).
    push_for_notification(
        user_id=user.pk, event_type=event_type, payload=payload, notification_id=notification.pk
    )

    return notification


@transaction.atomic
def notification_mark_all_read(*, user: BaseUser) -> int:
    """Marque toutes les notifications non lues de l'utilisateur comme lues."""
    return Notification.objects.filter(user=user, is_read=False).update(
        is_read=True, read_at=timezone.now()
    )


@transaction.atomic
def push_device_register(*, user: BaseUser, platform: str, token: str) -> "PushDevice":
    """
    Enregistre (ou réassigne) un token push. Idempotent : un token existant est
    rattaché au dernier utilisateur connecté sur l'appareil.
    """
    from apps.messaging.models import PushDevice

    device, created = PushDevice.objects.get_or_create(
        token=token,
        defaults={"user": user, "platform": platform},
    )
    if not created and (device.user_id != user.id or device.platform != platform or device.disabled_at):
        device.user = user
        device.platform = platform
        device.disabled_at = None  # un jeton ré-enregistré par l'app est de nouveau valable
        device.save(update_fields=["user", "platform", "disabled_at", "updated_at"])
    return device


@transaction.atomic
def push_device_unregister(*, user: BaseUser, token: str) -> None:
    from apps.messaging.models import PushDevice

    PushDevice.objects.filter(user=user, token=token).delete()


@transaction.atomic
def notification_mark_read(*, notification: Notification, user: BaseUser) -> Notification:
    if notification.user_id != user.id:
        raise ApplicationError("Accès refusé.")
    if notification.is_read:
        return notification
    notification.is_read = True
    notification.read_at = timezone.now()
    notification.save(update_fields=["is_read", "read_at", "updated_at"])
    return notification


# ---------------------------------------------------------------------------
# Conversation purge & export (called from tasks)
# ---------------------------------------------------------------------------


@transaction.atomic
def conversation_purge_messages(*, conversation: Conversation) -> None:
    from django.utils import timezone as tz

    now = tz.now()
    Message.objects.filter(conversation=conversation).update(
        content="",
        deleted_at=now,
    )
    conversation.scheduled_purge_at = None
    conversation.save(update_fields=["scheduled_purge_at", "updated_at"])


@transaction.atomic
def conversation_export_generate(*, export_id=None, conversation_id=None) -> ConversationExport:
    import json
    import uuid

    from django.utils import timezone as tz

    from apps.messaging.serializers import MessageOutputSerializer

    if export_id:
        export = ConversationExport.objects.select_related("conversation").get(id=export_id)
        conversation = export.conversation
    else:
        conversation = Conversation.objects.get(id=conversation_id)
        export = ConversationExport.objects.create(conversation=conversation)

    messages = Message.objects.filter(conversation=conversation).order_by("created_at")
    export_data = {
        "conversation_id": str(conversation.id),
        "exported_at": tz.now().isoformat(),
        "messages": MessageOutputSerializer(messages, many=True).data,
    }

    json_bytes = json.dumps(export_data, ensure_ascii=False, default=str).encode("utf-8")
    pdf_bytes = _generate_export_pdf(export_data)

    for content, filename, content_type, attr in [
        (json_bytes, f"export_{conversation.id}.json", "application/json", "json_file"),
        (pdf_bytes, f"export_{conversation.id}.pdf", "application/pdf", "pdf_file"),
    ]:
        from django.core.files.base import ContentFile

        cf = ContentFile(content, name=filename)
        file_obj = File.objects.create(
            original_file_name=filename,
            file_name=f"{uuid.uuid4()}_{filename}",
            file_type=content_type,
        )
        file_obj.file.save(file_obj.file_name, cf, save=True)
        file_obj.upload_finished_at = tz.now()
        file_obj.save(update_fields=["upload_finished_at"])
        setattr(export, attr, file_obj)

    export.completed_at = tz.now()
    export.save(update_fields=["json_file", "pdf_file", "completed_at", "updated_at"])
    return export


def _generate_export_pdf(data: dict) -> bytes:
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, height - 50, f"Export — {data['conversation_id']}")
    c.setFont("Helvetica", 10)
    c.drawString(50, height - 70, f"Exporté le : {data['exported_at']}")

    y = height - 110
    c.setFont("Helvetica", 9)
    for msg in data.get("messages", []):
        if y < 60:
            c.showPage()
            y = height - 50
        sender = msg.get("sender_name", "?")
        content = msg.get("content") or "[message supprimé]"
        created = str(msg.get("created_at", ""))[:19]
        c.drawString(50, y, f"[{created}] {sender}: {content}"[:120])
        y -= 15

    c.save()
    buffer.seek(0)
    return buffer.read()
