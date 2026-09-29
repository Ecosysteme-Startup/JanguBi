from django.contrib import admin

from apps.invitations.models import ClergyInvitation


@admin.register(ClergyInvitation)
class ClergyInvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "node", "status", "expires_at", "created_at")
    list_filter = ("status",)
    search_fields = ("email",)
    raw_id_fields = ("node", "invited_by", "accepted_by", "revoked_by")
    exclude = ("token_hash",)
