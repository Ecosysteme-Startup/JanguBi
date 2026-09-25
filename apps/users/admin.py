from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.users.models import BaseUser, Profile


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = _("Profil")
    fields = ("first_name", "last_name", "title", "date_of_birth", "phone", "avatar")


@admin.register(BaseUser)
class BaseUserAdmin(admin.ModelAdmin):
    """Exploitation seulement : l'identité et les accès se gèrent dans Keycloak, les offices
    dans l'application (nominations)."""

    list_display = ("email", "full_name", "etat_de_vie", "statut_verification", "is_active", "created_at")
    list_filter = ("is_active", "etat_de_vie", "degre_ordre", "statut_verification", "is_staff")
    search_fields = ("email", "profile__first_name", "profile__last_name", "phone_number")
    ordering = ("-created_at",)
    inlines = [ProfileInline]
    raw_id_fields = ("paroisse_suivie", "incardination_node", "institut_node", "verified_by")
    fieldsets = (
        (_("Identité"), {"fields": ("email", "phone_number", "keycloak_sub")}),
        (
            _("Personne"),
            {"fields": ("etat_de_vie", "degre_ordre", "incardination_node", "institut_node", "paroisse_suivie")},
        ),
        (_("Vérification"), {"fields": ("statut_verification", "verification_note", "verified_by", "verified_at")}),
        (_("Compte"), {"fields": ("is_active", "is_verified", "is_staff", "is_superuser")}),
        (_("Conformité"), {"fields": ("consent_version", "consent_at", "last_seen_on", "last_mfa_on")}),
        (_("Technique"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    readonly_fields = ("keycloak_sub", "consent_version", "consent_at", "last_seen_on", "last_mfa_on", "created_at", "updated_at")

    @admin.display(description=_("Nom complet"))
    def full_name(self, obj: BaseUser) -> str:
        profile = getattr(obj, "profile", None)
        return f"{profile.first_name} {profile.last_name}".strip() if profile else "-"
