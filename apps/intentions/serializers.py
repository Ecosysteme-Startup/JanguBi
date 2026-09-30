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
    requested_date = serializers.DateField(
        required=False, allow_null=True, default=None, help_text="null : « Pas de date précise »"
    )
    requested_mass = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")


class ParishFilterSerializer(serializers.Serializer):
    node = serializers.UUIDField(help_text="Paroisse")
    status = serializers.ChoiceField(choices=IntentionStatus.choices, required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)


class DayFilterSerializer(serializers.Serializer):
    node = serializers.UUIDField(help_text="Paroisse")
    date = serializers.DateField()


class SettingsInputSerializer(serializers.Serializer):
    node = serializers.UUIDField(help_text="Paroisse")
    max_per_mass = serializers.IntegerField(
        min_value=1, max_value=50, allow_null=True, help_text="1 à 50 ; null = pas de plafond"
    )


class MassCapKeySerializer(serializers.Serializer):
    node = serializers.UUIDField(help_text="Paroisse")
    place_id = serializers.IntegerField(help_text="Lieu de la messe")
    start_time = serializers.TimeField(help_text="Heure de la messe (10:00)")
    weekday = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=6,
        help_text="Horaire hebdomadaire : 0 = lundi … 6 = dimanche (exclusif avec date)",
    )
    date = serializers.DateField(required=False, allow_null=True, help_text="Messe datée (exclusif avec weekday)")


class MassCapInputSerializer(MassCapKeySerializer):
    max_intentions = serializers.IntegerField(
        min_value=1, max_value=50, allow_null=True, help_text="1 à 50 ; null = pas de plafond pour cette messe"
    )


class MassCapOutputSerializer(serializers.Serializer):
    id = serializers.CharField()
    place_id = serializers.IntegerField()
    start_time = serializers.TimeField()
    weekday = serializers.IntegerField(allow_null=True)
    date = serializers.DateField(allow_null=True)
    max_intentions = serializers.IntegerField(allow_null=True)


class SettingsFilterSerializer(serializers.Serializer):
    node = serializers.UUIDField(help_text="Paroisse")


class ScheduleInputSerializer(serializers.Serializer):
    scheduled_date = serializers.DateField()
    scheduled_time = serializers.TimeField(
        required=False, allow_null=True, default=None, help_text="Heure de la messe (plafond appliqué)"
    )
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
            "scheduled_time",
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


class DayMassOutputSerializer(serializers.Serializer):
    place_id = serializers.IntegerField()
    place_name = serializers.CharField()
    start_time = serializers.TimeField()
    label = serializers.CharField()  # type: ignore[assignment]  # champ d'API « label », masque Field.label
    language = serializers.CharField()
    note = serializers.CharField()
    intentions_count = serializers.IntegerField()
    max_intentions = serializers.IntegerField(allow_null=True, help_text="Plafond effectif ; null = sans plafond")
    cap_source = serializers.ChoiceField(choices=["paroisse", "horaire", "date"], help_text="Origine du plafond")
    remaining = serializers.IntegerField(allow_null=True, help_text="null = sans plafond")
    is_full = serializers.BooleanField()


class DayMassesOutputSerializer(serializers.Serializer):
    node = _RefSerializer()
    date = serializers.DateField()
    max_per_mass = serializers.IntegerField(allow_null=True, help_text="Plafond de la paroisse ; null = sans plafond")
    masses = DayMassOutputSerializer(many=True)
    without_time_count = serializers.IntegerField()


class SheetLineSerializer(serializers.Serializer):
    id = serializers.CharField()
    kind = serializers.CharField()
    kind_label = serializers.CharField()
    intention = serializers.CharField()
    announced_as = serializers.CharField()
    status = serializers.CharField()


class SheetOtherLineSerializer(SheetLineSerializer):
    scheduled_mass = serializers.CharField()


class SheetMassSerializer(DayMassOutputSerializer):
    intentions = SheetLineSerializer(many=True)


class SheetOutputSerializer(serializers.Serializer):
    node = _RefSerializer()
    date = serializers.DateField()
    masses = SheetMassSerializer(many=True)
    other_intentions = SheetOtherLineSerializer(many=True)


class SettingsOutputSerializer(serializers.Serializer):
    node = serializers.CharField()
    max_per_mass = serializers.IntegerField(allow_null=True)
