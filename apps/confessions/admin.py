from django.contrib import admin

from apps.confessions.models import ConfessionBooking, ConfessionSlot, ConfessionSlotRule


@admin.register(ConfessionSlotRule)
class ConfessionSlotRuleAdmin(admin.ModelAdmin):
    list_display = ["id", "priest", "place", "weekday", "start_time", "end_time", "slot_minutes", "is_active"]
    list_filter = ["is_active", "weekday"]
    raw_id_fields = ["priest", "place"]


@admin.register(ConfessionSlot)
class ConfessionSlotAdmin(admin.ModelAdmin):
    list_display = ["id", "priest", "place", "starts_at", "status"]
    list_filter = ["status"]
    raw_id_fields = ["rule", "priest", "place"]


@admin.register(ConfessionBooking)
class ConfessionBookingAdmin(admin.ModelAdmin):
    """Lecture seule : l'administration voit un rendez-vous, jamais plus (il n'y a rien d'autre)."""

    list_display = ["id", "slot", "status", "created_at"]
    list_filter = ["status"]
    readonly_fields = ["slot", "person", "status", "cancelled_at", "cancel_message", "created_at"]
    exclude = ["reminder_day_sent_at", "reminder_hours_sent_at"]

    def has_add_permission(self, request, obj=None) -> bool:  # type: ignore[no-untyped-def]
        return False

    def has_change_permission(self, request, obj=None) -> bool:  # type: ignore[no-untyped-def]
        return False
