from django.contrib import admin

from apps.agenda.models import Event, EventRegistration


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "event_type", "start_at", "scope_node", "organizer")
    list_filter = ("event_type",)
    search_fields = ("title", "description")
    raw_id_fields = ("organizer", "scope_node", "scope_place")


@admin.register(EventRegistration)
class EventRegistrationAdmin(admin.ModelAdmin):
    list_display = ("event", "user", "registered_at")
    raw_id_fields = ("event", "user")
