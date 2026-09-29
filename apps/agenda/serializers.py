from typing import Any

from django.utils import timezone
from rest_framework import serializers

from apps.agenda.models import Event, EventRegistration


class EventOutputSerializer(serializers.ModelSerializer):
    node_id = serializers.UUIDField(source="scope_node_id", read_only=True, allow_null=True)
    node_name = serializers.SerializerMethodField()
    place_id = serializers.IntegerField(source="scope_place_id", read_only=True, allow_null=True)
    registrations_count = serializers.IntegerField(read_only=True, default=0)
    seats_taken = serializers.IntegerField(
        read_only=True, default=0, help_text="Places réservées (somme des personnes)"
    )
    seats_remaining = serializers.SerializerMethodField(help_text="Vide : pas de jauge")
    is_full = serializers.SerializerMethodField()
    registrations_open = serializers.SerializerMethodField(help_text="Ni annulé, ni terminé, ni clos")
    is_registered = serializers.BooleanField(read_only=True, default=False)
    my_seats = serializers.IntegerField(read_only=True, default=None, allow_null=True, help_text="Mon inscription")
    my_note = serializers.CharField(read_only=True, default=None, allow_null=True, help_text="Ma remarque")
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
            "registration_closes_at",
            "registrations_count",
            "seats_taken",
            "seats_remaining",
            "is_full",
            "registrations_open",
            "is_registered",
            "my_seats",
            "my_note",
            "is_cancelled",
        ]

    def get_node_name(self, obj: Event) -> str | None:
        return obj.scope_node.name if obj.scope_node else None

    def get_seats_remaining(self, obj: Event) -> int | None:
        if obj.max_participants is None:
            return None
        return max(obj.max_participants - (getattr(obj, "seats_taken", 0) or 0), 0)

    def get_is_full(self, obj: Event) -> bool:
        return self.get_seats_remaining(obj) == 0

    def get_registrations_open(self, obj: Event) -> bool:
        now = timezone.now()
        closes_at = obj.registration_closes_at
        return obj.cancelled_at is None and obj.end_at > now and (closes_at is None or closes_at > now)


class RegistrationOutputSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(read_only=True)
    full_name = serializers.SerializerMethodField()
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = EventRegistration
        fields = ["id", "user_id", "full_name", "email", "seats", "note", "registered_at"]

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
    # « from » et « to » sont des mots réservés en Python : déclarés dans get_fields.

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields["from"] = serializers.DateField(required=False, help_text="Début de période (jour inclus)")
        fields["to"] = serializers.DateField(required=False, help_text="Fin de période (jour inclus)")
        return fields

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("from") and attrs.get("to") and attrs["from"] > attrs["to"]:
            raise serializers.ValidationError({"to": "La fin de période doit suivre son début."})
        return attrs


class RegisterInputSerializer(serializers.Serializer):
    seats = serializers.IntegerField(min_value=1, max_value=10, default=1, help_text="Nombre de personnes (1 à 10)")
    note = serializers.CharField(
        max_length=300, required=False, allow_blank=True, default="", help_text="Remarque, lue par les organisateurs"
    )


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
    registration_closes_at = serializers.DateTimeField(required=False, allow_null=True)


class EventUpdateInputSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    event_type = serializers.ChoiceField(choices=Event.EventType.choices, required=False)
    start_at = serializers.DateTimeField(required=False)
    end_at = serializers.DateTimeField(required=False)
    location = serializers.CharField(max_length=300, required=False, allow_blank=True)
    max_participants = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    registration_closes_at = serializers.DateTimeField(required=False, allow_null=True)


def registrations_csv_rows(registrations: Any) -> list[list[str]]:
    rows = [["Nom", "E-mail", "Personnes", "Remarque", "Inscrit le"]]
    for r in registrations:
        rows.append(
            [
                RegistrationOutputSerializer().get_full_name(r),
                r.user.email,
                str(r.seats),
                _csv_safe(r.note),
                timezone.localtime(r.registered_at).strftime("%d/%m/%Y %H:%M"),
            ]
        )
    return rows


def _csv_safe(value: str) -> str:
    """Neutralise l'injection de formule (tableur) : une saisie libre ne commence pas par = + - @."""
    return f"'{value}" if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value
