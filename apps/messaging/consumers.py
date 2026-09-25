from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache


def _payload(event: dict) -> dict:
    return {k: v for k, v in event.items() if k != "type"}


class ConversationConsumer(AsyncJsonWebsocketConsumer):
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
        await self._mark_read()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        handlers = {
            "message.send": self.handle_send,
            "message.read": self.handle_read,
            "message.react": self.handle_react,
            "typing.start": self.handle_typing_start,
            "typing.stop": self.handle_typing_stop,
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


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            await self.close(code=4001)
            return

        self.user = user
        self.group_name = f"user_{user.id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "notification.read":
            await self._mark_notification_read(content.get("notification_id"))

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
