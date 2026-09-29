import datetime
import uuid
from typing import Any
from urllib.parse import urlencode

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.documents.models import DocumentRequest, DocumentRequestStatusLog, InternalNote

V1_STATUS_CHOICES = DocumentRequest.Status.choices


# --- Entrées -------------------------------------------------------------------------------


class RequestCreateInputSerializer(serializers.Serializer):
    target_node_id = serializers.UUIDField(help_text="Paroisse où le sacrement a été célébré (RG-02)")
    document_type = serializers.ChoiceField(choices=DocumentRequest.DocumentType.choices)
    document_type_free = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    reason = serializers.ChoiceField(choices=DocumentRequest.RequestReason.choices)
    reason_free = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    requester_last_name = serializers.CharField(max_length=100)
    requester_first_names = serializers.CharField(max_length=200)
    date_of_birth = serializers.DateField()
    place_of_birth = serializers.CharField(max_length=200)
    contact_phone = serializers.CharField(max_length=30)
    contact_email = serializers.EmailField()
    registered_last_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    registered_first_names = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    father_last_name = serializers.CharField(max_length=100)
    mother_last_name = serializers.CharField(max_length=100)
    sacrament_approximate_date = serializers.CharField(max_length=20)
    sacrament_location = serializers.CharField(max_length=200)
    additional_info = serializers.CharField(required=False, allow_blank=True, default="")
    document_details = serializers.DictField(
        child=serializers.CharField(allow_blank=True), required=False, default=dict
    )
    pickup_mode = serializers.ChoiceField(
        choices=DocumentRequest.PickupMode.choices, default=DocumentRequest.PickupMode.SECRETARIAT
    )
    consent_given = serializers.BooleanField()
    attachment_file_id = serializers.IntegerField(required=False, allow_null=True)


class SupplementInputSerializer(serializers.Serializer):
    additional_info = serializers.CharField(required=False, allow_blank=True, default="")
    document_details = serializers.DictField(child=serializers.CharField(allow_blank=True), required=False)
    attachment_file_id = serializers.IntegerField(required=False, allow_null=True)


class TransitionInputSerializer(serializers.Serializer):
    message = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Motif (rejet), complément attendu, ou message de retrait",
    )
    pickup_place_id = serializers.IntegerField(
        required=False, allow_null=True, help_text="mark-ready : lieu de retrait"
    )
    pickup_hours = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class RegisterRefInputSerializer(serializers.Serializer):
    register_volume = serializers.CharField(max_length=40, required=False, allow_blank=True)
    register_page = serializers.CharField(max_length=20, required=False, allow_blank=True)
    register_number = serializers.CharField(max_length=40, required=False, allow_blank=True)
    register_marginal_notes = serializers.CharField(required=False, allow_blank=True)


class NoteInputSerializer(serializers.Serializer):
    content = serializers.CharField()


class QueueFilterSerializer(serializers.Serializer):
    node = serializers.UUIDField(required=False)
    status = serializers.ChoiceField(choices=V1_STATUS_CHOICES, required=False)
    document_type = serializers.ChoiceField(choices=DocumentRequest.DocumentType.choices, required=False)
    search = serializers.CharField(required=False, help_text="Référence ou nom du demandeur")
    overdue = serializers.BooleanField(required=False, default=False)
    reason = serializers.ChoiceField(choices=DocumentRequest.RequestReason.choices, required=False)
    assignee = serializers.CharField(
        required=False, help_text="« me » (moi), « none » (à assigner) ou l'identifiant d'une personne"
    )
    received_from = serializers.DateField(required=False, help_text="Reçue à partir de (inclus)")
    received_to = serializers.DateField(required=False, help_text="Reçue jusqu'au (inclus)")

    def validate_assignee(self, value: str) -> str:
        if value in ("me", "none"):
            return value
        try:
            return str(uuid.UUID(value))
        except ValueError as exc:
            raise serializers.ValidationError("Attendu : « me », « none » ou un identifiant.") from exc

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        start, end = attrs.get("received_from"), attrs.get("received_to")
        if start and end and start > end:
            raise serializers.ValidationError({"received_to": "La fin de période précède son début."})
        return attrs


class AssignInputSerializer(serializers.Serializer):
    assignee_id = serializers.UUIDField(allow_null=True, help_text="Personne de l'équipe, ou null pour « à assigner »")


class RequesterFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=V1_STATUS_CHOICES, required=False)


class NodeQuerySerializer(serializers.Serializer):
    node = serializers.UUIDField(required=False)


# --- Sorties -------------------------------------------------------------------------------


class NodeBriefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class PickupSerializer(serializers.Serializer):
    mode = serializers.CharField()
    place_name = serializers.CharField(allow_null=True)
    place_address = serializers.CharField(allow_null=True)
    hours = serializers.CharField()
    message = serializers.CharField()
    original_notice = serializers.CharField()


def person_name(user: Any) -> str:
    """Nom affiché d'une personne (profil), à défaut son adresse ; « » si inconnue."""
    if user is None:
        return ""
    profile = getattr(user, "profile", None)
    name = f"{getattr(profile, 'first_name', '')} {getattr(profile, 'last_name', '')}".strip()
    return name or user.email


class StatusLogSerializer(serializers.ModelSerializer):
    """Historique vu du fidèle : jamais le nom des membres de l'équipe."""

    class Meta:
        model = DocumentRequestStatusLog
        fields = ["from_status", "to_status", "comment", "created_at"]


class ProcessorStatusLogSerializer(StatusLogSerializer):
    """Historique vu de la paroisse : auteur de chaque changement."""

    changed_by_id = serializers.UUIDField(read_only=True, allow_null=True)
    changed_by_name = serializers.SerializerMethodField()
    by_requester = serializers.SerializerMethodField(help_text="Changement fait par le fidèle lui-même")

    class Meta(StatusLogSerializer.Meta):
        fields = [*StatusLogSerializer.Meta.fields, "changed_by_id", "changed_by_name", "by_requester"]

    def get_changed_by_name(self, obj: DocumentRequestStatusLog) -> str:
        return person_name(obj.changed_by)

    def get_by_requester(self, obj: DocumentRequestStatusLog) -> bool:
        return obj.changed_by_id is not None and obj.changed_by_id == obj.request.requester_id


class AttachmentOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    content_type = serializers.CharField()
    size = serializers.IntegerField(allow_null=True, help_text="Octets ; null si le fichier est illisible")
    uploaded_at = serializers.DateTimeField()
    url = serializers.CharField(help_text="Lien de consultation personnel, à durée limitée")
    expires_at = serializers.DateTimeField()


def _pickup(obj: DocumentRequest) -> dict[str, Any]:
    from apps.documents.services import ORIGINAL_NOTICE

    return {
        "mode": obj.pickup_mode,
        "place_name": obj.pickup_place.name if obj.pickup_place else None,
        "place_address": obj.pickup_place.address if obj.pickup_place else None,
        "hours": obj.pickup_hours,
        "message": obj.pickup_message,
        "original_notice": ORIGINAL_NOTICE,
    }


_ESTIMATED_STATUSES = (
    DocumentRequest.Status.SUBMITTED,
    DocumentRequest.Status.UNDER_VERIFICATION,
    DocumentRequest.Status.INFO_REQUESTED,
)


class _BaseOutputSerializer(serializers.ModelSerializer):
    target_node = serializers.SerializerMethodField()
    document_type_label = serializers.CharField(source="get_document_type_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    reason_label = serializers.CharField(source="get_reason_display", read_only=True)

    def get_target_node(self, obj: DocumentRequest) -> dict[str, Any] | None:
        node = obj.target_node
        return {"id": node.pk, "name": node.name} if node else None


class RequesterOutputSerializer(_BaseOutputSerializer):
    """Vue du fidèle : jamais les notes internes ni les références du registre (EF-ACT-02, -05)."""

    pickup = serializers.SerializerMethodField()
    history = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    indicative_days = serializers.SerializerMethodField(
        help_text="Délai indicatif (jours) : type d'acte, sinon paroisse, sinon réglage hérité, sinon défaut"
    )
    estimated_ready_on = serializers.SerializerMethodField(
        help_text="Mise à disposition estimée (indicative) ; null une fois l'acte prêt ou la demande close"
    )

    class Meta:
        model = DocumentRequest
        fields = [
            "id",
            "reference",
            "document_type",
            "document_type_label",
            "document_type_free",
            "reason",
            "reason_label",
            "reason_free",
            "status",
            "status_label",
            "target_node",
            "requester_last_name",
            "requester_first_names",
            "date_of_birth",
            "place_of_birth",
            "contact_phone",
            "contact_email",
            "registered_last_name",
            "registered_first_names",
            "father_last_name",
            "mother_last_name",
            "sacrament_approximate_date",
            "sacrament_location",
            "additional_info",
            "document_details",
            "rejection_reason",
            "pickup",
            "history",
            "can_cancel",
            "indicative_days",
            "estimated_ready_on",
            "created_at",
            "updated_at",
            "closed_at",
        ]

    def get_pickup(self, obj: DocumentRequest) -> dict[str, Any] | None:
        return PickupSerializer(_pickup(obj)).data if obj.status == DocumentRequest.Status.READY_FOR_PICKUP else None

    @extend_schema_field(StatusLogSerializer(many=True))
    def get_history(self, obj: DocumentRequest) -> list[dict[str, Any]]:
        if not self.context.get("with_history"):
            return []
        return list(StatusLogSerializer(obj.status_logs.all(), many=True).data)

    def get_can_cancel(self, obj: DocumentRequest) -> bool:
        return obj.status in (DocumentRequest.Status.SUBMITTED, DocumentRequest.Status.INFO_REQUESTED)

    def _resolver(self) -> Any:
        from apps.documents.services import SlaResolver

        # Un résolveur par réponse (réglages chargés une fois), pas une requête par ligne.
        root: Any = self.parent if self.parent is not None else self
        resolver = getattr(root, "_sla_resolver", None)
        if resolver is None:
            resolver = SlaResolver()
            root._sla_resolver = resolver
        return resolver

    def get_indicative_days(self, obj: DocumentRequest) -> int:
        return self._resolver().indicative_days_for(
            obj.target_node.path if obj.target_node else None, obj.document_type
        )

    def get_estimated_ready_on(self, obj: DocumentRequest) -> datetime.date | None:
        from django.utils import timezone

        if obj.status not in _ESTIMATED_STATUSES or obj.created_at is None:
            return None
        estimate = timezone.localdate(obj.created_at) + datetime.timedelta(days=self.get_indicative_days(obj))
        # Jamais une date passée : une demande en retard reste « estimée » au jour même.
        return max(estimate, timezone.localdate())


class QueueItemSerializer(_BaseOutputSerializer):
    requester_name = serializers.SerializerMethodField()
    age_days = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    assigned_to_id = serializers.UUIDField(read_only=True, allow_null=True)
    assigned_to_name = serializers.SerializerMethodField()

    class Meta:
        model = DocumentRequest
        fields = [
            "id",
            "reference",
            "document_type",
            "document_type_label",
            "reason",
            "reason_label",
            "reason_free",
            "status",
            "status_label",
            "target_node",
            "requester_name",
            "assigned_to_id",
            "assigned_to_name",
            "age_days",
            "is_overdue",
            "created_at",
            "updated_at",
        ]

    def get_requester_name(self, obj: DocumentRequest) -> str:
        return f"{obj.requester_last_name} {obj.requester_first_names}".strip()

    def get_assigned_to_name(self, obj: DocumentRequest) -> str | None:
        return person_name(obj.assigned_to) if obj.assigned_to_id else None

    def get_age_days(self, obj: DocumentRequest) -> int | None:
        from apps.documents.selectors import age_days

        return age_days(obj)

    def get_is_overdue(self, obj: DocumentRequest) -> bool:
        from apps.documents.selectors import is_overdue
        from apps.documents.services import SlaResolver

        # Un résolveur par réponse (réglages chargés une fois), pas une requête par ligne.
        root: Any = self.parent if self.parent is not None else self
        resolver = getattr(root, "_sla_resolver", None)
        if resolver is None:
            resolver = SlaResolver()
            root._sla_resolver = resolver
        return is_overdue(obj, resolver=resolver)


class ProcessorOutputSerializer(RequesterOutputSerializer):
    """Vue de la paroisse : identité complète, registre, lieu de retrait."""

    register = serializers.SerializerMethodField()
    assigned_to_id = serializers.UUIDField(read_only=True, allow_null=True)
    assigned_to_name = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()
    history = serializers.SerializerMethodField()

    class Meta(RequesterOutputSerializer.Meta):
        fields = [
            *RequesterOutputSerializer.Meta.fields,
            "register",
            "assigned_to_id",
            "assigned_to_name",
            "pickup_mode",
            "attachments",
        ]

    def get_assigned_to_name(self, obj: DocumentRequest) -> str | None:
        return person_name(obj.assigned_to) if obj.assigned_to_id else None

    @extend_schema_field(ProcessorStatusLogSerializer(many=True))
    def get_history(self, obj: DocumentRequest) -> list[dict[str, Any]]:
        if not self.context.get("with_history"):
            return []
        return list(ProcessorStatusLogSerializer(obj.status_logs.all(), many=True).data)

    @extend_schema_field(AttachmentOutputSerializer(many=True))
    def get_attachments(self, obj: DocumentRequest) -> list[dict[str, Any]]:
        """Pièces du fidèle, avec un lien personnel à durée limitée. Sans demande HTTP ni
        utilisateur dans le contexte (usage interne), aucune pièce n'est exposée."""
        from django.conf import settings
        from django.urls import reverse
        from django.utils import timezone

        from apps.documents.services import attachment_access_sign

        request = self.context.get("request")
        user = getattr(request, "user", None)
        if request is None or not getattr(user, "is_authenticated", False):
            return []
        expires_at = timezone.now() + datetime.timedelta(seconds=settings.DOCUMENTS_ATTACHMENT_URL_TTL)
        rows = []
        for attachment in obj.attachments.all():
            if attachment.attachment_type != DocumentRequest.AttachmentType.USER_SUPPORTING:
                continue
            file_obj = attachment.file
            path = reverse(
                "api:staff-documents:attachment",
                kwargs={"request_id": obj.pk, "attachment_id": attachment.pk},
            )
            token = attachment_access_sign(attachment=attachment, user=user)
            rows.append(
                {
                    "id": attachment.pk,
                    "name": file_obj.original_file_name,
                    "content_type": file_obj.file_type,
                    "size": _file_size(file_obj),
                    "uploaded_at": attachment.created_at,
                    "url": request.build_absolute_uri(f"{path}?{urlencode({'token': token})}"),
                    "expires_at": expires_at,
                }
            )
        return list(AttachmentOutputSerializer(rows, many=True).data)

    def get_register(self, obj: DocumentRequest) -> dict[str, str]:
        return {
            "volume": obj.register_volume,
            "page": obj.register_page,
            "number": obj.register_number,
            "marginal_notes": obj.register_marginal_notes,
        }

    def get_pickup(self, obj: DocumentRequest) -> dict[str, Any] | None:
        return PickupSerializer(_pickup(obj)).data


def _file_size(file_obj: Any) -> int | None:
    if not file_obj.file:
        return None
    try:
        return int(file_obj.file.size)
    except (OSError, ValueError):
        return None


class NoteOutputSerializer(serializers.ModelSerializer):
    author_id = serializers.UUIDField(read_only=True, allow_null=True)
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = InternalNote
        fields = ["id", "author_id", "author_name", "content", "created_at"]

    def get_author_name(self, obj: InternalNote) -> str:
        return person_name(obj.author)


class AssigneeOutputSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj: Any) -> str:
        return person_name(obj)


class CountsOutputSerializer(serializers.Serializer):
    counts = serializers.DictField(child=serializers.IntegerField())
    total = serializers.IntegerField()


class StatsOutputSerializer(CountsOutputSerializer):
    median_days_to_collect = serializers.FloatField(allow_null=True)
    overdue = serializers.IntegerField()


# --- Délais par type d'acte (Paramètres de la paroisse) ------------------------------------


class TypeDelayItemOutputSerializer(serializers.Serializer):
    document_type = serializers.ChoiceField(choices=DocumentRequest.DocumentType.choices)
    document_type_label = serializers.CharField()
    days = serializers.IntegerField(allow_null=True, help_text="Délai du type (jours ouvrés) ; null : délai global")


class TypeDelaysOutputSerializer(serializers.Serializer):
    node_id = serializers.UUIDField()
    default_days = serializers.IntegerField(
        help_text="Délai appliqué aux types sans réglage propre (paroisse, sinon hérité, sinon défaut)"
    )
    items = TypeDelayItemOutputSerializer(many=True)


class TypeDelayItemInputSerializer(serializers.Serializer):
    document_type = serializers.ChoiceField(
        choices=[c for c in DocumentRequest.DocumentType.choices if c[0] != DocumentRequest.DocumentType.OTHER]
    )
    days = serializers.IntegerField(
        allow_null=True, min_value=1, max_value=90, help_text="Jours ouvrés ; null : retirer (délai global)"
    )


class TypeDelaysUpdateInputSerializer(serializers.Serializer):
    items = TypeDelayItemInputSerializer(many=True)

    def validate_items(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        types = [item["document_type"] for item in value]
        if len(types) != len(set(types)):
            raise serializers.ValidationError("Chaque type d'acte ne peut figurer qu'une fois.")
        return value
