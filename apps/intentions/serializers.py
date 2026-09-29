from typing import Any

from rest_framework import serializers

from apps.hierarchy.persons import full_name
from apps.intentions.enums import OFFERING_NOTICE, IntentionKind, IntentionStatus
from apps.intentions.models import MassIntention

# --- Entrées ------------------------------------------------------------------------------


class IntentionCreateInputSerializer(serializers.Serializer):
    node = serializers.UUIDField(help_text="Paroisse")
    place_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    kind = serializers.ChoiceField(choices=IntentionKind.choices)
    intention = serializers.CharField(max_length=500)
    is_anonymous = serializers.BooleanField(default=False, help_text="Annoncée sans mon nom")
    requested_date = serializers.DateField()
    requested_mass = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")


class ParishFilterSerializer(serializers.Serializer):
    node = serializers.UUIDField(help_text="Paroisse")
    status = serializers.ChoiceField(choices=IntentionStatus.choices, required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)


class ScheduleInputSerializer(serializers.Serializer):
    scheduled_date = serializers.DateField()
    scheduled_mass = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    place_id = serializers.IntegerField(required=False, allow_null=True, default=None)


class DeclineInputSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)


# --- Sorties ------------------------------------------------------------------------------


class _RefSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()


class MassIntentionOutputSerializer(serializers.ModelSerializer):
    """Vue du fidèle. Aucun montant : ``notice`` rappelle que l'offrande se remet à la paroisse."""

    parish = serializers.SerializerMethodField()
    place = serializers.SerializerMethodField()
    notice = serializers.SerializerMethodField()

    class Meta:
        model = MassIntention
        fields = [
            "id",
            "parish",
            "place",
            "kind",
            "intention",
            "is_anonymous",
            "requested_date",
            "requested_mass",
            "status",
            "scheduled_date",
            "scheduled_mass",
            "refusal_reason",
            "celebrated_at",
            "cancelled_at",
            "created_at",
            "notice",
        ]

    def get_parish(self, obj: MassIntention) -> dict[str, Any]:
        return {"id": str(obj.node_id), "name": obj.node.name}

    def get_place(self, obj: MassIntention) -> dict[str, Any] | None:
        return {"id": str(obj.place_id), "name": obj.place.name} if obj.place else None

    def get_notice(self, obj: MassIntention) -> str:
        return OFFERING_NOTICE


class StaffMassIntentionOutputSerializer(MassIntentionOutputSerializer):
    requester_name = serializers.SerializerMethodField(help_text="Nom du demandeur (secrétariat seulement)")
    announced_as = serializers.SerializerMethodField(help_text="Nom à annoncer, ou « Une personne » si anonyme")

    class Meta(MassIntentionOutputSerializer.Meta):
        fields = [
            *[f for f in MassIntentionOutputSerializer.Meta.fields if f != "notice"],
            "requester_name",
            "announced_as",
            "decided_at",
        ]

    def get_requester_name(self, obj: MassIntention) -> str:
        if obj.requester is None:
            return "Compte supprimé"
        return full_name(obj.requester) or "Fidèle"

    def get_announced_as(self, obj: MassIntention) -> str:
        if obj.is_anonymous or obj.requester is None:
            return "Une personne"
        return full_name(obj.requester) or "Une personne"


class NoticeOutputSerializer(serializers.Serializer):
    notice = serializers.CharField()
