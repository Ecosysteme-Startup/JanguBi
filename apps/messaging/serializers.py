from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.messaging.models import (
    Conversation,
    ConversationExport,
    Message,
    MessageAttachment,
    MessageBlock,
    MessageReaction,
    MessagingAvailability,
    Notification,
)


class MessagingCguStatusSerializer(serializers.Serializer):
    accepted = serializers.BooleanField()
    accepted_at = serializers.DateTimeField(allow_null=True)


class ConversationParticipantSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.SerializerMethodField()
    email = serializers.EmailField()

    def get_full_name(self, obj) -> str:
        profile = getattr(obj, "profile", None)
        if profile:
            return f"{profile.first_name} {profile.last_name}".strip() or obj.email
        return obj.email


class LastMessageSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    sender_id = serializers.UUIDField(help_text="Expéditeur (pour l'aperçu « Vous : »)")
    content = serializers.CharField(allow_null=True)
    sent_at = serializers.DateTimeField(source="created_at")


class ConversationOutputSerializer(serializers.ModelSerializer):
    participant_a = ConversationParticipantSerializer(read_only=True)
    participant_b = ConversationParticipantSerializer(read_only=True)
    unread_count = serializers.IntegerField(default=0)
    last_message = serializers.SerializerMethodField()
    confession_notice = serializers.SerializerMethodField(
        help_text="Bandeau permanent : pas de confession par message (EF-PRE-05, RG-08)"
    )

    class Meta:
        model = Conversation
        fields = [
            "id",
            "participant_a",
            "participant_b",
            "last_message",
            "last_message_at",
            "is_archived",
            "cgu_accepted_by_a",
            "cgu_accepted_by_b",
            "scheduled_purge_at",
            "unread_count",
            "confession_notice",
            "created_at",
        ]

    def get_confession_notice(self, obj) -> str:
        from apps.messaging.services import CONFESSION_NOTICE

        return CONFESSION_NOTICE

    @extend_schema_field(LastMessageSerializer(allow_null=True))
    def get_last_message(self, obj):
        msg = obj.messages.filter(deleted_at__isnull=True).order_by("-created_at").first()
        if msg is None:
            return None
        return LastMessageSerializer(msg).data


class ConversationCreateInputSerializer(serializers.Serializer):
    priest_user_id = serializers.UUIDField()


class MessageReactionOutputSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.id", read_only=True)

    class Meta:
        model = MessageReaction
        fields = ["id", "user_id", "emoji", "created_at"]


class MessageAttachmentOutputSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    file_name = serializers.CharField(source="file.original_file_name", read_only=True)

    class Meta:
        model = MessageAttachment
        fields = ["id", "url", "file_name"]

    def get_url(self, obj) -> str:
        return obj.file.url


class MessageOutputSerializer(serializers.ModelSerializer):
    sender_id = serializers.UUIDField(source="sender.id", read_only=True)
    sender_name = serializers.SerializerMethodField()
    reactions = MessageReactionOutputSerializer(many=True, read_only=True)
    attachments = MessageAttachmentOutputSerializer(many=True, read_only=True)
    reply_to_id = serializers.UUIDField(
        source="reply_to.id", read_only=True, allow_null=True
    )
    is_deleted = serializers.BooleanField(read_only=True)

    class Meta:
        model = Message
        fields = [
            "id",
            "sender_id",
            "sender_name",
            "content",
            "content_type",
            "client_message_id",
            "reply_to_id",
            "read_at",
            "deleted_at",
            "is_deleted",
            "reactions",
            "attachments",
            "created_at",
        ]

    def get_sender_name(self, obj) -> str:
        profile = getattr(obj.sender, "profile", None)
        if profile:
            return f"{profile.first_name} {profile.last_name}".strip() or obj.sender.email
        return obj.sender.email

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.is_deleted:
            data["content"] = None
        return data


class MessageSendInputSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=4000)
    client_message_id = serializers.UUIDField(required=False, allow_null=True)
    reply_to_id = serializers.UUIDField(required=False, allow_null=True)


class MessageListInputSerializer(serializers.Serializer):
    before_id = serializers.UUIDField(required=False)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=100, default=30)


class ReactInputSerializer(serializers.Serializer):
    emoji = serializers.CharField(max_length=10)


class BlockOutputSerializer(serializers.ModelSerializer):
    blocked_id = serializers.UUIDField(source="blocked.id", read_only=True)
    blocked_name = serializers.SerializerMethodField()

    class Meta:
        model = MessageBlock
        fields = ["id", "blocked_id", "blocked_name", "created_at"]

    def get_blocked_name(self, obj) -> str:
        profile = getattr(obj.blocked, "profile", None)
        if profile:
            return f"{profile.first_name} {profile.last_name}".strip() or obj.blocked.email
        return obj.blocked.email


class BlockCreateInputSerializer(serializers.Serializer):
    blocked_user_id = serializers.UUIDField()


class ExportOutputSerializer(serializers.ModelSerializer):
    json_url = serializers.SerializerMethodField()
    pdf_url = serializers.SerializerMethodField()

    class Meta:
        model = ConversationExport
        fields = ["id", "json_url", "pdf_url", "completed_at", "created_at"]

    def get_json_url(self, obj) -> str | None:
        return obj.json_file.url if obj.json_file else None

    def get_pdf_url(self, obj) -> str | None:
        return obj.pdf_file.url if obj.pdf_file else None


class NotificationOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "event_type", "payload", "is_read", "read_at", "created_at"]


class NotificationUnreadCountSerializer(serializers.Serializer):
    unread = serializers.IntegerField()


class PushDeviceInputSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=["ios", "android", "web"])
    token = serializers.CharField(max_length=512)


class PushDeviceOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    platform = serializers.CharField()
    created_at = serializers.DateTimeField()


class AvailabilitySerializer(serializers.ModelSerializer):
    reply_windows = serializers.ListField(child=serializers.DictField(), required=False)

    class Meta:
        model = MessagingAvailability
        fields = ["accepts_new_conversations", "absent_until", "reply_windows", "note"]

    def validate_reply_windows(self, value):
        for window in value:
            if set(window) != {"weekday", "start", "end"} or not 0 <= int(window["weekday"]) <= 6:
                raise serializers.ValidationError("Chaque plage : {weekday: 0-6, start: 'HH:MM', end: 'HH:MM'}.")
        return value


class PriestOfficeOutputSerializer(serializers.Serializer):
    code = serializers.SlugField(help_text="Code de l'office (cure, vicaire_paroissial, aumonier…)")
    label = serializers.CharField(help_text="Libellé de l'office : Curé, Vicaire paroissial…")  # type: ignore[assignment]  # drf-stubs: champ « label » vs Field.label


class ReachablePriestOutputSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(source="user.id")
    full_name = serializers.SerializerMethodField()
    nodes = serializers.SerializerMethodField()
    availability = AvailabilitySerializer(allow_null=True)
    office = PriestOfficeOutputSerializer(
        allow_null=True, help_text="Office de la nomination active principale (paroisse suivie d'abord)"
    )

    def get_full_name(self, row) -> str:
        profile = getattr(row["user"], "profile", None)
        name = f"{getattr(profile, 'first_name', '')} {getattr(profile, 'last_name', '')}".strip()
        return name or "Prêtre"

    def get_nodes(self, row) -> list[dict]:
        return [{"id": str(n.pk), "name": n.name, "type": n.type.code} for n in row["nodes"]]
