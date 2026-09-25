import datetime
import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.files.models import File
from apps.messaging.fields import EncryptedTextField
from apps.users.models import BaseUser


class PriestProfile(BaseModel):
    user = models.OneToOneField(
        BaseUser,
        on_delete=models.CASCADE,
        related_name="priest_profile",
    )
    accepts_pastoral_chat = models.BooleanField(default=False, db_index=True)
    cgu_accepted_at = models.DateTimeField(null=True, blank=True)
    ordination_year = models.PositiveSmallIntegerField(null=True, blank=True)
    bio = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = _("Profil Prêtre")
        verbose_name_plural = _("Profils Prêtres")

    def __str__(self) -> str:
        return f"PriestProfile({self.user_id})"


class MessagingCguAcceptance(BaseModel):
    """
    Acceptation GLOBALE (par utilisateur) des CGU de messagerie.

    Historiquement l'acceptation n'existait que par conversation
    (Conversation.cgu_accepted_by_a/_b) : chaque nouvelle conversation redemandait
    les CGU et renvoyait un 403 surprise. Une ligne ici vaut acceptation pour
    TOUTES les conversations (les flags par conversation restent honorés en OR).
    """

    user = models.OneToOneField(
        BaseUser,
        on_delete=models.CASCADE,
        related_name="messaging_cgu",
    )
    accepted_at = models.DateTimeField()

    class Meta:
        verbose_name = _("Acceptation CGU messagerie")
        verbose_name_plural = _("Acceptations CGU messagerie")

    def __str__(self) -> str:
        return f"MessagingCguAcceptance({self.user_id})"


class Conversation(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # participant_a.id < participant_b.id (UUID string comparison) — canonical ordering
    participant_a = models.ForeignKey(
        BaseUser,
        on_delete=models.PROTECT,
        related_name="conversations_as_a",
    )
    participant_b = models.ForeignKey(
        BaseUser,
        on_delete=models.PROTECT,
        related_name="conversations_as_b",
    )
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    is_archived = models.BooleanField(default=False)
    cgu_accepted_by_a = models.DateTimeField(null=True, blank=True)
    cgu_accepted_by_b = models.DateTimeField(null=True, blank=True)
    scheduled_purge_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = _("Conversation")
        verbose_name_plural = _("Conversations")
        constraints = [
            models.UniqueConstraint(
                fields=["participant_a", "participant_b"],
                name="unique_conversation_pair",
            ),
        ]
        indexes = [
            models.Index(
                fields=["participant_a", "-last_message_at"],
                name="conv_a_last_msg_idx",
            ),
            models.Index(
                fields=["participant_b", "-last_message_at"],
                name="conv_b_last_msg_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Conversation({self.participant_a_id} ↔ {self.participant_b_id})"


class MessageBlock(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    blocker = models.ForeignKey(
        BaseUser,
        on_delete=models.CASCADE,
        related_name="blocks_sent",
    )
    blocked = models.ForeignKey(
        BaseUser,
        on_delete=models.CASCADE,
        related_name="blocks_received",
    )

    class Meta:
        verbose_name = _("Blocage")
        verbose_name_plural = _("Blocages")
        constraints = [
            models.UniqueConstraint(
                fields=["blocker", "blocked"],
                name="unique_block_pair",
            ),
        ]

    def __str__(self) -> str:
        return f"Block({self.blocker_id} → {self.blocked_id})"


class Message(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class ContentType(models.TextChoices):
        TEXT = "text", _("Texte")
        MEDIA = "media", _("Média")
        SYSTEM = "system", _("Système")

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        BaseUser,
        on_delete=models.PROTECT,
        related_name="sent_messages",
    )
    content = EncryptedTextField(blank=True, default="")
    content_type = models.CharField(
        max_length=10,
        choices=ContentType.choices,
        default=ContentType.TEXT,
    )
    # Idempotency key — client generates UUID, server deduplicates
    client_message_id = models.UUIDField(
        unique=True,
        null=True,
        blank=True,
        default=uuid.uuid4,
        db_index=True,
    )
    reply_to = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="replies",
    )
    read_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Message")
        verbose_name_plural = _("Messages")
        indexes = [
            # Critical for cursor pagination O(1)
            models.Index(
                fields=["conversation", "-created_at"],
                name="msg_conv_created_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Message({self.id}, conv={self.conversation_id})"

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class MessageAttachment(BaseModel):
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.ForeignKey(
        File,
        on_delete=models.PROTECT,
        related_name="message_attachments",
    )
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Pièce jointe")
        verbose_name_plural = _("Pièces jointes")


class MessageReaction(BaseModel):
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="reactions",
    )
    user = models.ForeignKey(
        BaseUser,
        on_delete=models.CASCADE,
        related_name="message_reactions",
    )
    emoji = models.CharField(max_length=10)

    class Meta:
        verbose_name = _("Réaction")
        verbose_name_plural = _("Réactions")
        constraints = [
            models.UniqueConstraint(
                fields=["message", "user", "emoji"],
                name="unique_message_reaction",
            ),
        ]


class ConversationExport(BaseModel):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="exports",
    )
    requested_by = models.ForeignKey(
        BaseUser,
        null=True,
        on_delete=models.SET_NULL,
        related_name="requested_exports",
    )
    json_file = models.ForeignKey(
        File,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="export_json",
    )
    pdf_file = models.ForeignKey(
        File,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="export_pdf",
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Export Conversation")
        verbose_name_plural = _("Exports Conversations")


class Notification(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        BaseUser,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    event_type = models.CharField(max_length=50)
    payload = models.JSONField(default=dict)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Notification")
        verbose_name_plural = _("Notifications")
        indexes = [
            models.Index(
                fields=["user", "is_read", "-created_at"],
                name="notif_user_unread_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Notification({self.user_id}, {self.event_type})"


class NotificationPreference(BaseModel):
    """Préférences de notification d'une personne (EF-PAROI-08). Absente = valeurs par défaut."""

    user = models.OneToOneField(BaseUser, on_delete=models.CASCADE, related_name="notification_preference")
    in_app = models.BooleanField(_("dans l'application"), default=True)
    email = models.BooleanField(_("par e-mail"), default=True)
    topic_annonces = models.BooleanField(_("annonces de ma paroisse"), default=True)
    topic_evenements = models.BooleanField(_("rappels d'événements"), default=True)
    quiet_start = models.TimeField(_("début du silence"), default=datetime.time(22, 0))
    quiet_end = models.TimeField(_("fin du silence"), default=datetime.time(6, 0))

    class Meta:
        verbose_name = _("Préférences de notification")
        verbose_name_plural = _("Préférences de notification")

    def __str__(self) -> str:
        return f"Préférences({self.user_id})"


class PushDevice(BaseModel):
    """
    Token d'appareil pour les notifications push (app mobile React Native).
    On enregistre les tokens dès maintenant ; l'envoi FCM/APNs viendra avec
    l'app. Un token est unique et se réassigne au dernier utilisateur connecté
    sur l'appareil.
    """

    class Platform(models.TextChoices):
        IOS = "ios", _("iOS")
        ANDROID = "android", _("Android")
        WEB = "web", _("Web")

    user = models.ForeignKey(
        BaseUser,
        on_delete=models.CASCADE,
        related_name="push_devices",
    )
    platform = models.CharField(max_length=10, choices=Platform.choices)
    token = models.CharField(max_length=512, unique=True)

    class Meta:
        verbose_name = _("Appareil push")
        verbose_name_plural = _("Appareils push")

    def __str__(self) -> str:
        return f"PushDevice({self.user_id}, {self.platform})"


class ClergicalMessage(BaseModel):
    """Encrypted message between clergy members (distinct from the pastoral Conversation model)."""

    class RecipientScope(models.TextChoices):
        INDIVIDUAL = "individual", _("Individuel")
        PARISH_CLERGY = "parish_clergy", _("Clergé de la paroisse")
        DIOCESE_CLERGY = "diocese_clergy", _("Clergé du diocèse")
        PROVINCE_BISHOPS = "province_bishops", _("Évêques de la province")

    sender = models.ForeignKey(
        BaseUser,
        on_delete=models.CASCADE,
        related_name="sent_clerical_messages",
    )
    recipient_scope = models.CharField(
        _("portée"),
        max_length=20,
        choices=RecipientScope.choices,
        default=RecipientScope.INDIVIDUAL,
        db_index=True,
    )
    scope_id = models.IntegerField(
        _("ID de la portée"),
        null=True,
        blank=True,
        help_text="ID de la paroisse, du diocèse ou de la province selon recipient_scope.",
    )
    individual_recipient = models.ForeignKey(
        BaseUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_clerical_messages",
    )
    subject = models.CharField(_("sujet"), max_length=200)
    body = EncryptedTextField(_("corps"))
    read_at = models.DateTimeField(_("lu le"), null=True, blank=True)

    class Meta:
        verbose_name = _("Message inter-clergé")
        verbose_name_plural = _("Messages inter-clergé")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["individual_recipient", "-created_at"], name="clerical_msg_rcpt_idx"),
            models.Index(fields=["sender", "-created_at"], name="clerical_msg_sender_idx"),
        ]

    def __str__(self) -> str:
        return f"ClergicalMessage({self.sender_id} → {self.recipient_scope})"
