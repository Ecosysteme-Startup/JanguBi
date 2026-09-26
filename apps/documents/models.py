import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.files.models import File
from apps.users.models import BaseUser


class DocumentRequest(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class DocumentType(models.TextChoices):
        BAPTISM = "baptism", _("Certificat de baptême")
        FIRST_COMMUNION = "first_communion", _("Attestation de première communion")
        CONFIRMATION = "confirmation", _("Attestation de confirmation")
        RELIGIOUS_MARRIAGE = "religious_marriage", _("Attestation de mariage religieux")
        GODPARENT = "godparent", _("Attestation parrain / marraine")
        # Échappatoire : le registre paroissial contient des actes qui ne rentrent
        # dans aucune des cinq catégories ci-dessus. Le libellé réel est saisi par
        # le demandeur dans `document_type_free` (obligatoire dans ce cas).
        OTHER = "other", _("Autre document")

    class RequestReason(models.TextChoices):
        RELIGIOUS_MARRIAGE = "religious_marriage", _("Mariage religieux")
        GODPARENT = "godparent", _("Parrain / marraine")
        CATECHISM = "catechism", _("Inscription catéchèse")
        PARISH_FILE = "parish_file", _("Dossier paroissial")
        PERSONAL = "personal", _("Usage personnel")
        OTHER = "other", _("Autre")

    class Status(models.TextChoices):
        # Cycle V1 (SRS §8.1).
        SUBMITTED = "submitted", _("Soumise")
        UNDER_VERIFICATION = "under_verification", _("En vérification")
        INFO_REQUESTED = "info_requested", _("Complément demandé")
        READY_FOR_PICKUP = "ready_for_pickup", _("Prête à retirer")
        COLLECTED = "collected", _("Retirée")
        REJECTED = "rejected", _("Rejetée")
        CANCELLED = "cancelled", _("Annulée")

    class PickupMode(models.TextChoices):
        SECRETARIAT = "secretariat", _("Au secrétariat de la paroisse du sacrement")
        TRANSFER = "transfer_to_followed_parish", _("Transmis à ma paroisse")

    class AttachmentType(models.TextChoices):
        USER_SUPPORTING = "user_supporting", _("Justificatif fidèle")
        PARISH_FINAL = "parish_final", _("Document final paroisse")

    reference = models.CharField(max_length=30, unique=True, db_index=True)
    requester = models.ForeignKey(
        BaseUser,
        on_delete=models.PROTECT,
        related_name="document_requests",
    )
    document_type = models.CharField(max_length=30, choices=DocumentType.choices, db_index=True)
    # Précision libre, obligatoire uniquement quand document_type == OTHER. Calqué
    # sur reason_free : même longueur, même contrat (jamais NULL, chaîne vide sinon).
    document_type_free = models.CharField(max_length=255, blank=True, default="")
    reason = models.CharField(max_length=30, choices=RequestReason.choices)
    reason_free = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.SUBMITTED, db_index=True
    )
    assigned_to = models.ForeignKey(
        BaseUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_document_requests",
    )
    rejection_reason = models.TextField(blank=True, default="")

    # Bloc Identité
    requester_last_name = models.CharField(max_length=100)
    requester_first_names = models.CharField(max_length=200)
    date_of_birth = models.DateField()
    place_of_birth = models.CharField(max_length=200)

    # Bloc Contact
    contact_phone = models.CharField(max_length=30)
    contact_email = models.EmailField()

    # Bloc Recherche
    registered_last_name = models.CharField(max_length=100, blank=True, default="")
    registered_first_names = models.CharField(max_length=200, blank=True, default="")
    father_last_name = models.CharField(max_length=100)
    mother_last_name = models.CharField(max_length=100)
    # Paroisse du sacrement (RG-02) : nœud qui tient les registres.
    target_node = models.ForeignKey(
        "hierarchy.Node",
        on_delete=models.PROTECT,
        related_name="document_requests",
        verbose_name=_("paroisse du sacrement"),
    )
    pickup_mode = models.CharField(
        max_length=40,
        choices=PickupMode.choices,
        default=PickupMode.SECRETARIAT,
        db_default=PickupMode.SECRETARIAT,
    )
    pickup_place = models.ForeignKey(
        "hierarchy.PlaceOfWorship", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    pickup_hours = models.CharField(max_length=255, blank=True, default="", db_default="")
    pickup_message = models.TextField(blank=True, default="", db_default="")
    # Références du registre (EF-ACT-05) — jamais renvoyées au fidèle.
    register_volume = models.CharField(max_length=40, blank=True, default="", db_default="")
    register_page = models.CharField(max_length=20, blank=True, default="", db_default="")
    register_number = models.CharField(max_length=40, blank=True, default="", db_default="")
    register_marginal_notes = models.TextField(blank=True, default="", db_default="")
    closed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_reminded_at = models.DateTimeField(null=True, blank=True)
    attachments_purged_at = models.DateTimeField(null=True, blank=True)

    sacrament_approximate_date = models.CharField(max_length=20)
    sacrament_location = models.CharField(max_length=200)
    additional_info = models.TextField(blank=True, default="")

    # Champs dynamiques par type de document
    document_details = models.JSONField(default=dict, blank=True)

    consent_given = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("Demande de document")
        verbose_name_plural = _("Demandes de documents")
        indexes = [
            models.Index(fields=["requester", "-created_at"], name="docreq_requester_idx"),
            models.Index(fields=["status", "-created_at"], name="docreq_status_idx"),
            models.Index(fields=["document_type", "status"], name="docreq_type_status_idx"),
            models.Index(fields=["target_node", "status", "-created_at"], name="docreq_node_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.reference} — {self.get_document_type_display()} [{self.get_status_display()}]"


class DocumentRequestStatusLog(BaseModel):
    request = models.ForeignKey(
        DocumentRequest,
        on_delete=models.CASCADE,
        related_name="status_logs",
    )
    from_status = models.CharField(max_length=30, blank=True, default="")
    to_status = models.CharField(max_length=30)
    changed_by = models.ForeignKey(
        BaseUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="document_status_changes",
    )
    comment = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = _("Journal de statut")
        verbose_name_plural = _("Journaux de statut")
        indexes = [
            models.Index(fields=["request", "created_at"], name="doclog_request_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.request.reference}: {self.from_status} → {self.to_status}"


class DocumentRequestAttachment(BaseModel):
    request = models.ForeignKey(
        DocumentRequest,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.ForeignKey(
        File,
        on_delete=models.PROTECT,
        related_name="document_request_attachments",
    )
    uploaded_by = models.ForeignKey(
        BaseUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="document_attachments_uploaded",
    )
    attachment_type = models.CharField(
        max_length=20,
        choices=DocumentRequest.AttachmentType.choices,
        default=DocumentRequest.AttachmentType.USER_SUPPORTING,
    )
    label = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = _("Pièce jointe")
        verbose_name_plural = _("Pièces jointes")

    def __str__(self) -> str:
        return f"{self.request.reference} — {self.get_attachment_type_display()}"


class InternalNote(BaseModel):
    request = models.ForeignKey(
        DocumentRequest,
        on_delete=models.CASCADE,
        related_name="internal_notes",
    )
    author = models.ForeignKey(
        BaseUser,
        on_delete=models.PROTECT,
        related_name="document_internal_notes",
    )
    content = models.TextField()

    class Meta:
        verbose_name = _("Note interne")
        verbose_name_plural = _("Notes internes")

    def __str__(self) -> str:
        return f"Note — {self.request.reference} par {self.author_id}"


class DocumentSlaSetting(BaseModel):
    """Seuils de relance d'un nœud (EF-ACT-08). Le plus proche ancêtre réglé s'applique."""

    node = models.OneToOneField("hierarchy.Node", on_delete=models.CASCADE, related_name="document_sla")
    escalate_days = models.PositiveSmallIntegerField(_("relance de la paroisse (jours)"), default=7)
    requester_reminder_days = models.PositiveSmallIntegerField(_("relance du fidèle (jours)"), default=5)
    pickup_reminder_days = models.PositiveSmallIntegerField(_("rappel de retrait (jours)"), default=3)
    # Délai annoncé au fidèle (« mise à disposition estimée »). Vide : réglage hérité, sinon
    # DOCUMENTS_DEFAULT_INDICATIVE_DAYS. Indicatif, jamais un engagement.
    indicative_days = models.PositiveSmallIntegerField(
        _("délai indicatif annoncé au fidèle (jours)"), null=True, blank=True
    )

    class Meta:
        verbose_name = _("Délais de traitement")
        verbose_name_plural = _("Délais de traitement")

    def __str__(self) -> str:
        return f"Délais — {self.node}"
