from typing import Any

from rest_framework import serializers

from apps.agenda.models import Event, EventRegistration


class EventOutputSerializer(serializers.ModelSerializer):
    node_id = serializers.UUIDField(source="scope_node_id", read_only=True, allow_null=True)
    node_name = serializers.SerializerMethodField()
    place_id = serializers.IntegerField(source="scope_place_id", read_only=True, allow_null=True)
    registrations_count = serializers.IntegerField(read_only=True, default=0)
    is_full = serializers.SerializerMethodField()
    is_registered = serializers.BooleanField(read_only=True, default=False)
    is_cancelled = serializers.BooleanField(read_only=True)

    class Meta:
        model = Event
        fields = [
            "id",
            "title",
            "description",
            "event_type",
            "start_at",
            "end_at",
            "location",
            "node_id",
            "node_name",
            "place_id",
            "max_participants",
            "registrations_count",
            "is_full",
            "is_registered",
            "is_cancelled",
        ]

    def get_node_name(self, obj: Event) -> str | None:
        return obj.scope_node.name if obj.scope_node else None

    def get_is_full(self, obj: Event) -> bool:
        count = getattr(obj, "registrations_count", 0) or 0
        return obj.max_participants is not None and count >= obj.max_participants


class RegistrationOutputSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(read_only=True)
    full_name = serializers.SerializerMethodField()
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = EventRegistration
        fields = ["id", "user_id", "full_name", "email", "registered_at"]

    def get_full_name(self, obj: EventRegistration) -> str:
        profile = getattr(obj.user, "profile", None)
        return f"{getattr(profile, 'first_name', '')} {getattr(profile, 'last_name', '')}".strip()


class EventFilterSerializer(serializers.Serializer):
    node = serializers.UUIDField(required=False, help_text="Nœud (et son sous-arbre)")
    date_from = serializers.DateTimeField(required=False, help_text="Par défaut : maintenant")
    date_to = serializers.DateTimeField(required=False)
    type = serializers.ChoiceField(choices=Event.EventType.choices, required=False)


class StaffEventFilterSerializer(serializers.Serializer):
    node = serializers.UUIDField(required=False)
    include_past = serializers.BooleanField(default=False)


class EventCreateInputSerializer(serializers.Serializer):
    node_id = serializers.UUIDField(required=False, allow_null=True, help_text="Vide : événement global (plateforme)")
    place_id = serializers.IntegerField(required=False, allow_null=True)
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    event_type = serializers.ChoiceField(choices=Event.EventType.choices, default=Event.EventType.OTHER)
    start_at = serializers.DateTimeField()
    end_at = serializers.DateTimeField()
    location = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    max_participants = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class EventUpdateInputSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    event_type = serializers.ChoiceField(choices=Event.EventType.choices, required=False)
    start_at = serializers.DateTimeField(required=False)
    end_at = serializers.DateTimeField(required=False)
    location = serializers.CharField(max_length=300, required=False, allow_blank=True)
    max_participants = serializers.IntegerField(min_value=1, required=False, allow_null=True)


def registrations_csv_rows(registrations: Any) -> list[list[str]]:
    rows = [["Nom", "E-mail", "Inscrit le"]]
    for r in registrations:
        rows.append([RegistrationOutputSerializer().get_full_name(r), r.user.email, r.registered_at.strftime("%d/%m/%Y %H:%M")])
    return rows
