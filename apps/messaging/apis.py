from uuid import UUID

from django.shortcuts import get_object_or_404
from drf_spectacular.openapi import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin
from apps.api.pagination import LimitOffsetPagination, get_paginated_response
from apps.core.exceptions import ApplicationError
from apps.hierarchy.authz import HasCapability
from apps.messaging.models import Conversation, Message, MessageBlock, MessagingAvailability
from apps.messaging.permissions import (
    HasAcceptedMessagingCgu,
    IsBlockOwner,
    IsMessageSender,
    IsParticipant,
)
from apps.messaging.selectors import (
    block_list,
    conversation_get,
    conversation_list,
    export_list,
    message_list,
    messaging_cgu_get,
    notification_list,
    priests_reachable_for,
)
from apps.messaging.serializers import (
    AvailabilitySerializer,
    BlockCreateInputSerializer,
    BlockOutputSerializer,
    ClergicalMessageOutputSerializer,
    ClergicalMessageSendInputSerializer,
    ConversationCreateInputSerializer,
    ConversationOutputSerializer,
    ExportOutputSerializer,
    MessageListInputSerializer,
    MessageOutputSerializer,
    MessageSendInputSerializer,
    MessagingCguStatusSerializer,
    NotificationOutputSerializer,
    NotificationUnreadCountSerializer,
    PushDeviceInputSerializer,
    PushDeviceOutputSerializer,
    ReachablePriestOutputSerializer,
    ReactInputSerializer,
)
from apps.messaging.services import (
    availability_update,
    block_user,
    conversation_accept_cgu,
    conversation_archive,
    conversation_delete,
    conversation_export_request,
    conversation_get_or_create,
    message_delete,
    message_mark_read,
    message_react,
    message_send,
    message_unreact,
    messaging_cgu_accept,
    notification_mark_all_read,
    notification_mark_read,
    push_device_register,
    push_device_unregister,
    unblock_user,
)
from apps.users.models import BaseUser


def _error(exc: ApplicationError) -> Response:
    # Code HTTP porté par l'exception (403 pour un mineur, 400 par défaut) et code métier.
    return Response({"detail": exc.message, "code": exc.code}, status=exc.status_code)


# ---------------------------------------------------------------------------
# Prêtres joignables et disponibilités (EF-PRE-01, -07)
# ---------------------------------------------------------------------------


class PriestListApi(ApiAuthMixin, APIView):
    @extend_schema(
        responses={200: ReachablePriestOutputSerializer(many=True)},
        tags=["messaging"],
        summary="Prêtres joignables de ma paroisse suivie et des aumôneries du diocèse",
    )
    def get(self, request):
        return Response(ReachablePriestOutputSerializer(priests_reachable_for(user=request.user), many=True).data)


class AvailabilityApi(ApiAuthMixin, APIView):
    permission_classes = [IsAuthenticated, HasCapability("messagerie.recevoir_fideles")]

    @extend_schema(responses={200: AvailabilitySerializer}, tags=["messaging"], summary="Mes disponibilités (prêtre joignable)")
    def get(self, request):
        availability = MessagingAvailability.objects.filter(user=request.user).first() or MessagingAvailability(
            user=request.user
        )
        return Response(AvailabilitySerializer(availability).data)

    @extend_schema(
        request=AvailabilitySerializer,
        responses={200: AvailabilitySerializer},
        tags=["messaging"],
        summary="Modifier mes disponibilités (nouveaux échanges, absence, plages de réponse)",
    )
    def put(self, request):
        serializer = AvailabilitySerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        availability = availability_update(user=request.user, data=serializer.validated_data)
        return Response(AvailabilitySerializer(availability).data)


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


class MessagingCguApi(ApiAuthMixin, APIView):
    """CGU de messagerie globales : une acceptation vaut pour toutes les conversations."""

    @extend_schema(responses={200: MessagingCguStatusSerializer}, tags=["messaging"], summary="Statut d'acceptation des CGU de messagerie")
    def get(self, request):
        acceptance = messaging_cgu_get(user=request.user)
        data = {
            "accepted": acceptance is not None,
            "accepted_at": acceptance.accepted_at if acceptance else None,
        }
        return Response(MessagingCguStatusSerializer(data).data)

    @extend_schema(request=None, responses={200: MessagingCguStatusSerializer}, tags=["messaging"], summary="Accepter les CGU de messagerie (global, idempotent)")
    def post(self, request):
        acceptance = messaging_cgu_accept(user=request.user)
        data = {"accepted": True, "accepted_at": acceptance.accepted_at}
        return Response(MessagingCguStatusSerializer(data).data)


class ConversationListApi(ApiAuthMixin, APIView):
    @extend_schema(
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, description="Filtrer par nom ou email d'un participant"),
        ],
        responses={200: ConversationOutputSerializer(many=True)},
        tags=["messaging"],
        summary="Lister mes conversations",
    )
    def get(self, request):
        search = request.query_params.get("search") or None
        conversations = conversation_list(user=request.user, search=search)
        return Response(ConversationOutputSerializer(conversations, many=True).data)


class ConversationCreateApi(ApiAuthMixin, APIView):
    @extend_schema(request=ConversationCreateInputSerializer, responses={201: ConversationOutputSerializer}, tags=["messaging"], summary="Démarrer une conversation avec un prêtre")
    def post(self, request):
        serializer = ConversationCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        priest_user = get_object_or_404(BaseUser, id=serializer.validated_data["priest_user_id"])
        try:
            conversation, _ = conversation_get_or_create(fidele=request.user, priest=priest_user)
        except ApplicationError as exc:
            return _error(exc)
        return Response(ConversationOutputSerializer(conversation).data, status=status.HTTP_201_CREATED)


class ConversationCguApi(ApiAuthMixin, APIView):
    def get_permissions(self):
        return [IsAuthenticated(), IsParticipant()]

    @extend_schema(request=None, responses={200: ConversationOutputSerializer}, tags=["messaging"], summary="Accepter les CGU de messagerie")
    def post(self, request, conversation_id: UUID):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        self.check_object_permissions(request, conversation)
        try:
            conversation = conversation_accept_cgu(conversation=conversation, user=request.user)
        except ApplicationError as exc:
            return _error(exc)
        return Response(ConversationOutputSerializer(conversation).data)


class ConversationArchiveApi(ApiAuthMixin, APIView):
    def get_permissions(self):
        return [IsAuthenticated(), IsParticipant()]

    @extend_schema(request=None, responses={200: ConversationOutputSerializer}, tags=["messaging"], summary="Archiver une conversation")
    def post(self, request, conversation_id: UUID):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        self.check_object_permissions(request, conversation)
        conversation = conversation_archive(conversation=conversation, user=request.user)
        return Response(ConversationOutputSerializer(conversation).data)


class ConversationDetailApi(ApiAuthMixin, APIView):
    def get_permissions(self):
        return [IsAuthenticated(), IsParticipant()]

    @extend_schema(responses={200: ConversationOutputSerializer}, tags=["messaging"], summary="Récupérer le détail d'une conversation")
    def get(self, request, conversation_id: UUID):
        conversation = conversation_get(conversation_id=conversation_id, user=request.user)
        if conversation is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(ConversationOutputSerializer(conversation).data)

    @extend_schema(responses={204: None}, tags=["messaging"], summary="Supprimer une conversation")
    def delete(self, request, conversation_id: UUID):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        self.check_object_permissions(request, conversation)
        conversation_delete(conversation=conversation, user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ConversationExportApi(ApiAuthMixin, APIView):
    def get_permissions(self):
        return [IsAuthenticated(), IsParticipant()]

    @extend_schema(request=None, responses={201: ExportOutputSerializer}, tags=["messaging"], summary="Demander l'export d'une conversation")
    def post(self, request, conversation_id: UUID):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        self.check_object_permissions(request, conversation)
        export = conversation_export_request(conversation=conversation, user=request.user)
        return Response(ExportOutputSerializer(export).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: ExportOutputSerializer(many=True)}, tags=["messaging"], summary="Lister les exports d'une conversation")
    def get(self, request, conversation_id: UUID):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        self.check_object_permissions(request, conversation)
        exports = export_list(conversation=conversation)
        return Response(ExportOutputSerializer(exports, many=True).data)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class MessageListApi(ApiAuthMixin, APIView):
    def get_permissions(self):
        return [IsAuthenticated(), IsParticipant(), HasAcceptedMessagingCgu()]

    @extend_schema(
        parameters=[
            OpenApiParameter("before_id", OpenApiTypes.UUID, description="Charger les messages avant cet identifiant (pagination curseur)"),
            OpenApiParameter("limit", OpenApiTypes.INT, description="Nombre de messages à retourner (max 100, défaut 30)"),
        ],
        responses={200: MessageOutputSerializer(many=True)},
        tags=["messaging"],
        summary="Lister les messages d'une conversation",
    )
    def get(self, request, conversation_id: UUID):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        self.check_object_permissions(request, conversation)
        input_serializer = MessageListInputSerializer(data=request.query_params)
        input_serializer.is_valid(raise_exception=True)
        messages = message_list(conversation=conversation, **input_serializer.validated_data)
        return Response(MessageOutputSerializer(messages, many=True).data)


class MessageSendApi(ApiAuthMixin, APIView):
    def get_permissions(self):
        return [IsAuthenticated(), IsParticipant(), HasAcceptedMessagingCgu()]

    @extend_schema(request=MessageSendInputSerializer, responses={201: MessageOutputSerializer}, tags=["messaging"], summary="Envoyer un message")
    def post(self, request, conversation_id: UUID):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        self.check_object_permissions(request, conversation)
        serializer = MessageSendInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reply_to = None
        reply_to_id = serializer.validated_data.get("reply_to_id")
        if reply_to_id:
            reply_to = get_object_or_404(Message, id=reply_to_id, conversation=conversation)

        try:
            message = message_send(
                conversation=conversation,
                sender=request.user,
                content=serializer.validated_data["content"],
                client_message_id=serializer.validated_data.get("client_message_id"),
                reply_to=reply_to,
            )
        except ApplicationError as exc:
            return _error(exc)
        return Response(MessageOutputSerializer(message).data, status=status.HTTP_201_CREATED)


class MessageReadApi(ApiAuthMixin, APIView):
    def get_permissions(self):
        return [IsAuthenticated(), IsParticipant()]

    @extend_schema(request=None, responses={200: None}, tags=["messaging"], summary="Marquer les messages comme lus")
    def post(self, request, conversation_id: UUID):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        self.check_object_permissions(request, conversation)
        message_mark_read(conversation=conversation, reader=request.user)
        return Response({"status": "ok"})


class MessageDeleteApi(ApiAuthMixin, APIView):
    def get_permissions(self):
        return [IsAuthenticated(), IsMessageSender()]

    @extend_schema(responses={204: None}, tags=["messaging"], summary="Supprimer un message")
    def delete(self, request, message_id: UUID):
        message = get_object_or_404(Message, id=message_id)
        self.check_object_permissions(request, message)
        try:
            message_delete(message=message, user=request.user)
        except ApplicationError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MessageReactApi(ApiAuthMixin, APIView):
    def get_permissions(self):
        return [IsAuthenticated(), IsParticipant()]

    @extend_schema(request=ReactInputSerializer, responses={201: None}, tags=["messaging"], summary="Réagir à un message")
    def post(self, request, message_id: UUID):
        message = get_object_or_404(Message, id=message_id)
        self.check_object_permissions(request, message.conversation)
        serializer = ReactInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message_react(message=message, user=request.user, emoji=serializer.validated_data["emoji"])
        return Response(status=status.HTTP_201_CREATED)

    @extend_schema(request=ReactInputSerializer, responses={204: None}, tags=["messaging"], summary="Supprimer une réaction")
    def delete(self, request, message_id: UUID):
        message = get_object_or_404(Message, id=message_id)
        self.check_object_permissions(request, message.conversation)
        serializer = ReactInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message_unreact(message=message, user=request.user, emoji=serializer.validated_data["emoji"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


class BlockListCreateApi(ApiAuthMixin, APIView):
    @extend_schema(responses={200: BlockOutputSerializer(many=True)}, tags=["messaging"], summary="Lister mes blocages")
    def get(self, request):
        blocks = block_list(user=request.user)
        return Response(BlockOutputSerializer(blocks, many=True).data)

    @extend_schema(request=BlockCreateInputSerializer, responses={201: BlockOutputSerializer}, tags=["messaging"], summary="Bloquer un utilisateur")
    def post(self, request):
        serializer = BlockCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        blocked_user = get_object_or_404(BaseUser, id=serializer.validated_data["blocked_user_id"])
        try:
            block = block_user(blocker=request.user, blocked=blocked_user)
        except ApplicationError as exc:
            return _error(exc)
        return Response(BlockOutputSerializer(block).data, status=status.HTTP_201_CREATED)


class BlockDeleteApi(ApiAuthMixin, APIView):
    def get_permissions(self):
        return [IsAuthenticated(), IsBlockOwner()]

    @extend_schema(responses={204: None}, tags=["messaging"], summary="Débloquer un utilisateur")
    def delete(self, request, block_id: UUID):
        block = get_object_or_404(MessageBlock, id=block_id)
        self.check_object_permissions(request, block)
        try:
            unblock_user(blocker=request.user, blocked=block.blocked)
        except ApplicationError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class NotificationListApi(ApiAuthMixin, APIView):
    @extend_schema(
        parameters=[OpenApiParameter("unread_only", OpenApiTypes.BOOL, description="Si true, retourne uniquement les notifications non lues")],
        responses={200: NotificationOutputSerializer(many=True)},
        tags=["messaging"],
        summary="Lister mes notifications",
    )
    def get(self, request):
        unread_only = request.query_params.get("unread_only", "false").lower() == "true"
        notifications = notification_list(user=request.user, unread_only=unread_only)
        return Response(NotificationOutputSerializer(notifications, many=True).data)


class NotificationReadApi(ApiAuthMixin, APIView):
    @extend_schema(request=None, responses={200: NotificationOutputSerializer}, tags=["messaging"], summary="Marquer une notification comme lue")
    def post(self, request, notification_id: UUID):
        from apps.messaging.models import Notification

        notification = get_object_or_404(Notification, id=notification_id)
        try:
            notification = notification_mark_read(notification=notification, user=request.user)
        except ApplicationError as exc:
            return _error(exc)
        return Response(NotificationOutputSerializer(notification).data)


class NotificationReadAllApi(ApiAuthMixin, APIView):
    @extend_schema(
        request=None,
        responses={200: NotificationUnreadCountSerializer},
        tags=["notifications"],
        summary="Marquer toutes mes notifications comme lues",
    )
    def post(self, request):
        notification_mark_all_read(user=request.user)
        return Response(NotificationUnreadCountSerializer({"unread": 0}).data)


class NotificationUnreadCountApi(ApiAuthMixin, APIView):
    @extend_schema(
        responses={200: NotificationUnreadCountSerializer},
        tags=["notifications"],
        summary="Nombre de notifications non lues (badge)",
    )
    def get(self, request):
        count = notification_list(user=request.user, unread_only=True).count()
        return Response(NotificationUnreadCountSerializer({"unread": count}).data)


class PushDeviceApi(ApiAuthMixin, APIView):
    """Enregistrement des tokens push de l'app mobile (React Native)."""

    @extend_schema(
        request=PushDeviceInputSerializer,
        responses={201: PushDeviceOutputSerializer},
        tags=["notifications"],
        summary="Enregistrer un token push (idempotent, réassigne l'appareil)",
    )
    def post(self, request):
        serializer = PushDeviceInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = push_device_register(user=request.user, **serializer.validated_data)
        return Response(
            PushDeviceOutputSerializer(device).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        request=PushDeviceInputSerializer,
        responses={204: None},
        tags=["notifications"],
        summary="Désenregistrer un token push (déconnexion)",
    )
    def delete(self, request):
        token = request.data.get("token") or request.query_params.get("token")
        if not token:
            return Response(
                {"detail": "token requis."}, status=status.HTTP_400_BAD_REQUEST
            )
        push_device_unregister(user=request.user, token=token)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# ClergicalMessage endpoints
# ---------------------------------------------------------------------------


class ClergicalMessageSendApi(ApiAuthMixin, APIView):
    @extend_schema(
        request=ClergicalMessageSendInputSerializer,
        responses={201: ClergicalMessageOutputSerializer},
        tags=["messaging"],
        summary="Envoyer un message inter-clergé",
    )
    def post(self, request):
        serializer = ClergicalMessageSendInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            from apps.messaging.services import clerical_message_send
            msg = clerical_message_send(sender=request.user, **serializer.validated_data)
        except ApplicationError as exc:
            return _error(exc)
        return Response(ClergicalMessageOutputSerializer(msg).data, status=status.HTTP_201_CREATED)


class ClergicalMessageInboxApi(ApiAuthMixin, APIView):
    @extend_schema(
        parameters=[
            OpenApiParameter("limit", OpenApiTypes.INT, description="Nombre de résultats"),
            OpenApiParameter("offset", OpenApiTypes.INT, description="Offset de pagination"),
        ],
        responses={200: ClergicalMessageOutputSerializer(many=True)},
        tags=["messaging"],
        summary="Messages inter-clergé reçus",
    )
    def get(self, request):
        from apps.messaging.selectors import clerical_message_inbox
        msgs = clerical_message_inbox(user=request.user)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=ClergicalMessageOutputSerializer,
            queryset=msgs,
            request=request,
            view=self,
        )


class ClergicalMessageSentApi(ApiAuthMixin, APIView):
    @extend_schema(
        parameters=[
            OpenApiParameter("limit", OpenApiTypes.INT, description="Nombre de résultats"),
            OpenApiParameter("offset", OpenApiTypes.INT, description="Offset de pagination"),
        ],
        responses={200: ClergicalMessageOutputSerializer(many=True)},
        tags=["messaging"],
        summary="Messages inter-clergé envoyés",
    )
    def get(self, request):
        from apps.messaging.selectors import clerical_message_sent
        msgs = clerical_message_sent(user=request.user)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=ClergicalMessageOutputSerializer,
            queryset=msgs,
            request=request,
            view=self,
        )


class ClergicalMessageReadApi(ApiAuthMixin, APIView):
    @extend_schema(
        request=None,
        responses={200: ClergicalMessageOutputSerializer},
        tags=["messaging"],
        summary="Marquer un message inter-clergé comme lu",
    )
    def post(self, request, message_id: int):
        from apps.messaging.models import ClergicalMessage
        from apps.messaging.services import clerical_message_mark_read
        try:
            msg = ClergicalMessage.objects.get(pk=message_id, individual_recipient=request.user)
        except ClergicalMessage.DoesNotExist:
            return Response({"detail": "Message introuvable."}, status=status.HTTP_404_NOT_FOUND)
        try:
            msg = clerical_message_mark_read(message=msg, reader=request.user)
        except ApplicationError as exc:
            return _error(exc)
        return Response(ClergicalMessageOutputSerializer(msg).data)
