from django.contrib import admin

from apps.intentions.models import MassIntention


@admin.register(MassIntention)
class MassIntentionAdmin(admin.ModelAdmin):
    # Le texte de l'intention (donnée religieuse) n'est pas affiché dans la liste.
    list_display = ("id", "node", "requested_date", "status", "created_at")
    list_filter = ("status",)
    raw_id_fields = ("requester", "node", "place", "decided_by")
