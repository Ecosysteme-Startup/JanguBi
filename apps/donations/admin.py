"""Administration technique : lecture seule sur les dons (aucune modification des montants)."""

from django.contrib import admin

from apps.donations.models import CashCollection, Donation, DonationActivation, Fund, PaymentWebhookEvent, Payout


@admin.register(DonationActivation)
class DonationActivationAdmin(admin.ModelAdmin):
    list_display = ["node", "enabled", "authorization_ref", "authorization_date"]
    list_filter = ["enabled"]
    raw_id_fields = ["node"]


@admin.register(Fund)
class FundAdmin(admin.ModelAdmin):
    list_display = ["title", "node", "kind", "destination", "status", "starts_on", "ends_on"]
    list_filter = ["kind", "status", "destination"]
    raw_id_fields = ["node", "parent", "decided_by", "image"]


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = ["reference", "fund", "status", "channel", "created_at"]
    list_filter = ["status", "channel"]
    search_fields = ["reference"]
    exclude = ["donor", "donor_email"]  # données personnelles : non affichées dans l'admin

    def has_change_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False

    def has_delete_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False


@admin.register(CashCollection)
class CashCollectionAdmin(admin.ModelAdmin):
    list_display = ["mass_date", "mass_label", "node", "fund", "status"]
    list_filter = ["status"]
    raw_id_fields = ["node", "fund", "place", "entered_by", "validated_by"]


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ["external_ref", "provider", "node", "paid_at", "status"]
    list_filter = ["status", "provider"]


@admin.register(PaymentWebhookEvent)
class PaymentWebhookEventAdmin(admin.ModelAdmin):
    list_display = ["received_at", "provider", "status", "error_code", "signature_valid"]
    list_filter = ["status", "provider"]
    exclude = ["payload"]
