from django.contrib import admin
from django.utils import timezone

from apps.contact.models import PresentationRequest


@admin.register(PresentationRequest)
class PresentationRequestAdmin(admin.ModelAdmin):
    list_display = ["created_at", "full_name", "fonction", "paroisse", "diocese_node", "cure_informe", "handled_at"]
    list_filter = ["fonction", "cure_informe", ("handled_at", admin.EmptyFieldListFilter), "created_at"]
    search_fields = ["full_name", "paroisse", "email", "telephone"]
    raw_id_fields = ["diocese_node"]
    readonly_fields = ["created_at", "updated_at", "consented_at"]
    date_hierarchy = "created_at"
    actions = ["mark_handled"]

    @admin.action(description="Marquer comme traitées")
    def mark_handled(self, request, queryset):
        queryset.filter(handled_at__isnull=True).update(handled_at=timezone.now())
