from typing import Any

from rest_framework import serializers

from apps.documents.models import DocumentRequest, DocumentRequestStatusLog, InternalNote

V1_STATUS_CHOICES = [
    (value, label)
    for value, label in DocumentRequest.Status.choices
    if value not in (DocumentRequest.Status.VALIDATED, DocumentRequest.Status.DOCUMENT_DEPOSITED)
]


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
    document_details = serializers.DictField(child=serializers.CharField(allow_blank=True), required=False, default=dict)
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
        required=False, allow_blank=True, default="", help_text="Motif (rejet), complément attendu, ou message de retrait"
    )
    pickup_place_id = serializers.IntegerField(required=False, allow_null=True, help_text="mark-ready : lieu de retrait")
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


class StatusLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentRequestStatusLog
        fields = ["from_status", "to_status", "comment", "created_at"]


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


class _BaseOutputSerializer(serializers.ModelSerializer):
    target_node = serializers.SerializerMethodField()
    document_type_label = serializers.CharField(source="get_document_type_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    def get_target_node(self, obj: DocumentRequest) -> dict[str, Any] | None:
        node = obj.target_node
        return {"id": node.pk, "name": node.name} if node else None


class RequesterOutputSerializer(_BaseOutputSerializer):
    """Vue du fidèle : jamais les notes internes ni les références du registre (EF-ACT-02, -05)."""

    pickup = serializers.SerializerMethodField()
    history = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()

    class Meta:
        model = DocumentRequest
        fields = [
            "id",
            "reference",
            "document_type",
            "document_type_label",
            "document_type_free",
            "reason",
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
            "created_at",
            "updated_at",
            "closed_at",
        ]

    def get_pickup(self, obj: DocumentRequest) -> dict[str, Any] | None:
        return PickupSerializer(_pickup(obj)).data if obj.status == DocumentRequest.Status.READY_FOR_PICKUP else None

    def get_history(self, obj: DocumentRequest) -> list[dict[str, Any]]:
        if not self.context.get("with_history"):
            return []
        return list(StatusLogSerializer(obj.status_logs.all(), many=True).data)

    def get_can_cancel(self, obj: DocumentRequest) -> bool:
        return obj.status in (DocumentRequest.Status.SUBMITTED, DocumentRequest.Status.INFO_REQUESTED)


class QueueItemSerializer(_BaseOutputSerializer):
    requester_name = serializers.SerializerMethodField()
    age_days = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    assigned_to_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = DocumentRequest
        fields = [
            "id",
            "reference",
            "document_type",
            "document_type_label",
            "status",
            "status_label",
            "target_node",
            "requester_name",
            "assigned_to_id",
            "age_days",
            "is_overdue",
            "created_at",
            "updated_at",
        ]

    def get_requester_name(self, obj: DocumentRequest) -> str:
        return f"{obj.requester_last_name} {obj.requester_first_names}".strip()

    def get_age_days(self, obj: DocumentRequest) -> int | None:
        from apps.documents.selectors import age_days

        return age_days(obj)

    def get_is_overdue(self, obj: DocumentRequest) -> bool:
        from apps.documents.selectors import is_overdue

        return is_overdue(obj)


class ProcessorOutputSerializer(RequesterOutputSerializer):
    """Vue de la paroisse : identité complète, registre, lieu de retrait."""

    register = serializers.SerializerMethodField()
    assigned_to_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta(RequesterOutputSerializer.Meta):
        fields = [*RequesterOutputSerializer.Meta.fields, "register", "assigned_to_id", "pickup_mode"]

    def get_register(self, obj: DocumentRequest) -> dict[str, str]:
        return {
            "volume": obj.register_volume,
            "page": obj.register_page,
            "number": obj.register_number,
            "marginal_notes": obj.register_marginal_notes,
        }

    def get_pickup(self, obj: DocumentRequest) -> dict[str, Any] | None:
        return PickupSerializer(_pickup(obj)).data


class NoteOutputSerializer(serializers.ModelSerializer):
    author_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = InternalNote
        fields = ["id", "author_id", "content", "created_at"]


class CountsOutputSerializer(serializers.Serializer):
    counts = serializers.DictField(child=serializers.IntegerField())
    total = serializers.IntegerField()


class StatsOutputSerializer(CountsOutputSerializer):
    median_days_to_collect = serializers.FloatField(allow_null=True)
    overdue = serializers.IntegerField()
