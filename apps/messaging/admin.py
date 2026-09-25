from django.contrib import admin

from apps.messaging.models import (
    Conversation,
    ConversationExport,
    Message,
    MessageAttachment,
    MessageBlock,
    MessageReaction,
    Notification,
    PriestProfile,
)


@admin.register(PriestProfile)
class PriestProfileAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "accepts_pastoral_chat", "cgu_accepted_at", "ordination_year"]
    list_filter = ["accepts_pastoral_chat"]
    search_fields = ["user__email", "user__first_name", "user__last_name"]
    raw_id_fields = ["user"]


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ["id", "participant_a", "participant_b", "last_message_at", "is_archived", "scheduled_purge_at"]
    list_filter = ["is_archived"]
    search_fields = ["participant_a__email", "participant_b__email"]
    raw_id_fields = ["participant_a", "participant_b"]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    """Métadonnées seulement : aucun administrateur, Numerisen compris, ne lit le contenu (RG-09).

    Le contenu est exclu du formulaire et jamais chargé ; les messages ne sont ni créés ni
    modifiés depuis l'administration."""

    list_display = ["id", "conversation", "sender", "content_type", "read_at", "deleted_at", "created_at"]
    list_filter = ["content_type"]
    search_fields = ["sender__email"]
    exclude = ["content"]
    readonly_fields = ["conversation", "sender", "content_type", "reply_to", "read_at", "deleted_at"]

    def get_queryset(self, request):
        return super().get_queryset(request).defer("content")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MessageBlock)
class MessageBlockAdmin(admin.ModelAdmin):
    list_display = ["id", "blocker", "blocked", "created_at"]
    raw_id_fields = ["blocker", "blocked"]


@admin.register(MessageReaction)
class MessageReactionAdmin(admin.ModelAdmin):
    list_display = ["id", "message", "user", "emoji", "created_at"]
    raw_id_fields = ["message", "user"]


@admin.register(ConversationExport)
class ConversationExportAdmin(admin.ModelAdmin):
    """Un export contient la conversation : aucun lien vers ses fichiers (RG-09)."""

    list_display = ["id", "conversation", "requested_by", "completed_at", "created_at"]
    exclude = ["json_file", "pdf_file"]
    readonly_fields = ["conversation", "requested_by", "completed_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MessageAttachment)
class MessageAttachmentAdmin(admin.ModelAdmin):
    """Pièces d'une conversation : aucun lien vers le fichier depuis l'administration (RG-09)."""

    list_display = ["id", "message", "created_at"]
    exclude = ["file"]
    readonly_fields = ["message"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "event_type", "is_read", "read_at", "created_at"]
    list_filter = ["event_type", "is_read"]
    search_fields = ["user__email"]
    raw_id_fields = ["user"]
