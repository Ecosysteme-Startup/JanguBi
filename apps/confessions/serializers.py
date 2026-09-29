from typing import Any

from rest_framework import serializers

from apps.confessions.models import ConfessionBooking, ConfessionSlot, ConfessionSlotRule
from apps.confessions.selectors import booking_can_cancel


def _full_name(user: Any) -> str:
    profile = getattr(user, "profile", None)
    return f"{getattr(profile, 'first_name', '')} {getattr(profile, 'last_name', '')}".strip()


def initials(user: Any) -> str:
    """« Awa Marie Diop » → « A. D. » : le secrétariat organise sans identifier."""
    profile = getattr(user, "profile", None)
    first = (getattr(profile, "first_name", "") or "").strip()
    last = (getattr(profile, "last_name", "") or "").strip()
    parts = [f"{p[0].upper()}." for p in (first, last) if p]
    return " ".join(parts) or "—"


# --- Entrées ------------------------------------------------------------------------------


class SlotFilterSerializer(serializers.Serializer):
    node = serializers.UUIDField(required=False, help_text="Nœud (paroisse…) : sous-arbre compris")
    place = serializers.IntegerField(required=False, help_text="Lieu de culte")
    date_from = serializers.DateField(required=False, help_text="À partir de cette date (défaut : maintenant)")


class PlanningFilterSerializer(serializers.Serializer):
    node = serializers.UUIDField(required=False)
    date_from = serializers.DateField(
        required=False, help_text="Début de la fenêtre de 4 semaines (défaut : aujourd'hui)"
    )


class BookingCreateInputSerializer(serializers.Serializer):
    slot_id = serializers.IntegerField()


class RuleCreateInputSerializer(serializers.Serializer):
    place_id = serializers.IntegerField()
    weekday = serializers.IntegerField(min_value=0, max_value=6, help_text="0 = lundi … 6 = dimanche")
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    slot_minutes = serializers.IntegerField(min_value=5, max_value=60, default=10)
    valid_from = serializers.DateField(required=False, allow_null=True)
    valid_to = serializers.DateField(required=False, allow_null=True)


class SessionOpenInputSerializer(serializers.Serializer):
    place_id = serializers.IntegerField()
    date = serializers.DateField()
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    slot_minutes = serializers.IntegerField(min_value=5, max_value=60, default=10)
    priest_id = serializers.UUIDField(required=False, allow_null=True, default=None, help_text="Par défaut : moi")


class SlotCancelInputSerializer(serializers.Serializer):
    message = serializers.CharField(
        max_length=300, required=False, allow_blank=True, default="", help_text="Message transmis au réservant"
    )


class AttendanceInputSerializer(serializers.Serializer):
    attended = serializers.BooleanField()


# --- Sorties ------------------------------------------------------------------------------


class PlaceBriefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    address = serializers.CharField()
    node_id = serializers.UUIDField()


class SlotOutputSerializer(serializers.ModelSerializer):
    place = PlaceBriefSerializer()
    priest_name = serializers.SerializerMethodField()

    class Meta:
        model = ConfessionSlot
        fields = ["id", "starts_at", "ends_at", "status", "place", "priest_id", "priest_name"]

    def get_priest_name(self, obj: ConfessionSlot) -> str:
        return _full_name(obj.priest) or "Prêtre"


class BookingOutputSerializer(serializers.ModelSerializer):
    """Vue du fidèle : son rendez-vous. Aucun champ de contenu (RG-08)."""

    slot = SlotOutputSerializer()
    can_cancel = serializers.SerializerMethodField()

    class Meta:
        model = ConfessionBooking
        fields = ["id", "status", "slot", "cancel_message", "cancelled_at", "can_cancel", "created_at"]

    def get_can_cancel(self, obj: ConfessionBooking) -> bool:
        return booking_can_cancel(obj)


class RuleOutputSerializer(serializers.ModelSerializer):
    place = PlaceBriefSerializer()

    class Meta:
        model = ConfessionSlotRule
        fields = [
            "id",
            "place",
            "weekday",
            "start_time",
            "end_time",
            "slot_minutes",
            "valid_from",
            "valid_to",
            "is_active",
        ]


class PlanningBookingSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    person = serializers.CharField(help_text="Nom complet pour le prêtre du créneau, initiales pour le secrétariat")


class PlanningSlotSerializer(SlotOutputSerializer):
    booking = serializers.SerializerMethodField()
    is_mine = serializers.SerializerMethodField()

    class Meta(SlotOutputSerializer.Meta):
        fields = [*SlotOutputSerializer.Meta.fields, "is_mine", "booking"]

    def _viewer_id(self) -> Any:
        return self.context["request"].user.pk

    def get_is_mine(self, obj: ConfessionSlot) -> bool:
        return obj.priest_id == self._viewer_id()

    def get_booking(self, obj: ConfessionSlot) -> dict[str, Any] | None:
        bookings = getattr(obj, "active_bookings", [])
        if not bookings:
            return None
        booking = bookings[0]
        name = _full_name(booking.person) if obj.priest_id == self._viewer_id() else initials(booking.person)
        return dict(PlanningBookingSerializer({"id": booking.pk, "status": booking.status, "person": name or "—"}).data)
