import logging
from collections.abc import Awaitable, Callable
from typing import Any

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache

logger = logging.getLogger(__name__)


def _payload(event: dict) -> dict:
    return {k: v for k, v in event.items() if k != "type"}


class PresenceMixin:
    """Présence (docs/TEMPS-REEL.md) : chaque socket authentifiée compte une connexion ; le
    client envoie ``{"type": "presence.ping"}`` toutes les 25 s pour la garder vivante."""

    _presence_counted = False
    user: Any
    send_json: Callable[..., Awaitable[None]]

    # La présence est un confort : une panne du cache ne doit jamais fermer la socket.
    async def presence_join(self, user) -> None:
        from apps.messaging.services_presence import presence_connect

        try:
            await database_sync_to_async(presence_connect)(user=user)
            self._presence_counted = True
        except Exception:  # noqa: BLE001
            logger.warning("presence.connect_failed", exc_info=True)

    async def presence_leave(self) -> None:
        if not self._presence_counted:
            return
        from apps.messaging.services_presence import presence_disconnect

        self._presence_counted = False
        try:
            await database_sync_to_async(presence_disconnect)(user=self.user)
        except Exception:  # noqa: BLE001
            logger.warning("presence.disconnect_failed", exc_info=True)

    async def presence_ping(self) -> None:
        from apps.messaging.services_presence import presence_heartbeat

        try:
            await database_sync_to_async(presence_heartbeat)(user=self.user)
        except Exception:  # noqa: BLE001
            logger.warning("presence.heartbeat_failed", exc_info=True)
        await self.send_json({"type": "presence.pong"})

    # Diffusé aux interlocuteurs par services_presence.presence_broadcast.
    async def presence_changed(self, event: dict):
        await self.send_json({**_payload(event), "type": "presence.changed"})


class ConversationConsumer(PresenceMixin, AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            await self.close(code=4001)
            return

        conversation_id = self.scope["url_route"]["kwargs"]["conversation_id"]
        conversation = await self._get_conversation(conversation_id, user)
        if conversation is None:
            await self.close(code=4003)
            return

        self.conversation = conversation
        self.group_name = f"conv_{conversation.id}"
        self.user = user

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.presence_join(user)
        await self._mark_read()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        await self.presence_leave()

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        handlers = {
            "message.send": self.handle_send,
            "message.read": self.handle_read,
            "message.react": self.handle_react,
            "typing.start": self.handle_typing_start,
            "typing.stop": self.handle_typing_stop,
            "presence.ping": self.handle_presence_ping,
        }
        handler = handlers.get(msg_type)
        if handler:
            await handler(content)
        else:
            await self.send_json({"type": "error", "detail": f"Unknown type: {msg_type}"})

    async def handle_send(self, content: dict):
        from apps.messaging.services import message_send

        try:
            await database_sync_to_async(message_send)(
                conversation=self.conversation,
                sender=self.user,
                content=content.get("content", ""),
                client_message_id=content.get("client_message_id"),
            )
        except Exception as exc:
            await self.send_json({"type": "error", "detail": str(exc)})

    async def handle_read(self, content: dict):
        await self._mark_read()

    async def handle_react(self, content: dict):
        from apps.messaging.models import Message
        from apps.messaging.services import message_react, message_unreact

        message_id = content.get("message_id")
        emoji = content.get("emoji", "")
        action = content.get("action", "react")

        if message_id is None:
            await self.send_json({"type": "error", "detail": "message_id manquant"})
            return
        lookup_id = message_id  # rétréci : non-None garanti pour le lookup

        try:
            message = await database_sync_to_async(
                lambda: Message.objects.get(id=lookup_id, conversation=self.conversation)
            )()
            svc = message_react if action == "react" else message_unreact
            await database_sync_to_async(svc)(message=message, user=self.user, emoji=emoji)
        except Exception as exc:
            await self.send_json({"type": "error", "detail": str(exc)})

    async def handle_presence_ping(self, content: dict):
        await self.presence_ping()

    async def handle_typing_start(self, content: dict):
        cache.set(f"typing:{self.conversation.id}:{self.user.id}", 1, timeout=8)
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "conv_typing", "user_id": str(self.user.id), "is_typing": True},
        )

    async def handle_typing_stop(self, content: dict):
        cache.delete(f"typing:{self.conversation.id}:{self.user.id}")
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "conv_typing", "user_id": str(self.user.id), "is_typing": False},
        )

    # Channel layer event handlers (invoked by group_send from services)

    async def conv_message(self, event: dict):
        await self.send_json({
            "type": "message.received",
            "message": event.get("message"),
        })

    # `event["type"]` est la clé de dispatch Channels (« conv_typing ») : elle ne doit pas
    # écraser le type de la trame envoyée au client.
    async def conv_typing(self, event: dict):
        await self.send_json({**_payload(event), "type": "typing"})

    async def conv_read(self, event: dict):
        await self.send_json({**_payload(event), "type": "message.read"})

    # Helpers

    @database_sync_to_async
    def _get_conversation(self, conversation_id: str, user):
        from django.db.models import Q

        from apps.messaging.models import Conversation

        return (
            Conversation.objects.filter(pk=conversation_id)
            .filter(Q(participant_a=user) | Q(participant_b=user))
            .first()
        )

    @database_sync_to_async
    def _mark_read(self):
        from apps.messaging.services import message_mark_read

        message_mark_read(conversation=self.conversation, reader=self.user)


class NotificationConsumer(PresenceMixin, AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            await self.close(code=4001)
            return

        self.user = user
        self.group_name = f"user_{user.id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.presence_join(user)

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        await self.presence_leave()

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "notification.read":
            await self._mark_notification_read(content.get("notification_id"))
        elif content.get("type") == "presence.ping":
            await self.presence_ping()

    async def notification_push(self, event: dict):
        # `event["type"]` = "notification.push" (clé de dispatch Channels) : le
        # spreader APRÈS l'écrasait. On force "notification" comme type de frame.
        payload = {k: v for k, v in event.items() if k != "type"}
        await self.send_json({"type": "notification", **payload})

    @database_sync_to_async
    def _mark_notification_read(self, notification_id: str):
        from apps.messaging.models import Notification
        from apps.messaging.services import notification_mark_read

        try:
            notification = Notification.objects.get(id=notification_id, user=self.user)
            notification_mark_read(notification=notification, user=self.user)
        except Exception:
            pass
