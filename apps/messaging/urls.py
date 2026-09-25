from django.urls import path

from apps.messaging.apis import (
    AvailabilityApi,
    BlockDeleteApi,
    BlockListCreateApi,
    ConversationArchiveApi,
    ConversationCguApi,
    ConversationCreateApi,
    ConversationDetailApi,
    ConversationExportApi,
    ConversationListApi,
    MessageDeleteApi,
    MessageListApi,
    MessageReactApi,
    MessageReadApi,
    MessageSendApi,
    MessagingCguApi,
    NotificationListApi,
    NotificationReadApi,
    PriestListApi,
)

urlpatterns = [
    # Prêtres joignables et disponibilités (V1)
    path("priests/", PriestListApi.as_view(), name="priest-list"),
    path("availability/", AvailabilityApi.as_view(), name="availability"),
    # CGU messagerie (global, par utilisateur)
    path("cgu/", MessagingCguApi.as_view(), name="messaging-cgu"),
    # Conversations
    path("conversations/", ConversationListApi.as_view(), name="conversation-list"),
    path("conversations/create/", ConversationCreateApi.as_view(), name="conversation-create"),
    path("conversations/<uuid:conversation_id>/cgu/", ConversationCguApi.as_view(), name="conversation-cgu"),
    path("conversations/<uuid:conversation_id>/archive/", ConversationArchiveApi.as_view(), name="conversation-archive"),
    path("conversations/<uuid:conversation_id>/", ConversationDetailApi.as_view(), name="conversation-detail"),
    path("conversations/<uuid:conversation_id>/export/", ConversationExportApi.as_view(), name="conversation-export"),
    # Messages
    path("conversations/<uuid:conversation_id>/messages/", MessageListApi.as_view(), name="message-list"),
    path("conversations/<uuid:conversation_id>/messages/send/", MessageSendApi.as_view(), name="message-send"),
    path("conversations/<uuid:conversation_id>/read/", MessageReadApi.as_view(), name="message-read"),
    path("messages/<uuid:message_id>/", MessageDeleteApi.as_view(), name="message-delete"),
    path("messages/<uuid:message_id>/react/", MessageReactApi.as_view(), name="message-react"),
    # Blocks
    path("blocks/", BlockListCreateApi.as_view(), name="block-list-create"),
    path("blocks/<uuid:block_id>/", BlockDeleteApi.as_view(), name="block-delete"),
    # Notifications
    path("notifications/", NotificationListApi.as_view(), name="notification-list"),
    path("notifications/<uuid:notification_id>/read/", NotificationReadApi.as_view(), name="notification-read"),
]
