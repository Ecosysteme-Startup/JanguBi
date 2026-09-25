from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.users.models import (
    BaseUser,
    ClergySelfDeclaration,
    Membership,
    Profile,
    RoleAssignment,
    SecurityAuditLog,
)


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = _("Profil")
    fieldsets = (
        (None, {"fields": ("first_name", "last_name", "title", "avatar")}),
        (_("Contact"), {"fields": ("phone", "date_of_birth")}),
        (_("Paroisse"), {"fields": ("primary_parish",), "classes": ("collapse",)}),
    )


@admin.register(BaseUser)
class BaseUserAdmin(admin.ModelAdmin):
    list_display = ("email", "role", "full_name", "is_verified", "is_active", "is_staff", "created_at")
    list_filter = ("role", "is_active", "is_verified", "is_staff", "is_admin")
    search_fields = ("email", "profile__first_name", "profile__last_name", "phone_number")
    ordering = ("-created_at",)
    inlines = [ProfileInline]

    fieldsets = (
        (_("Identité & Rôle"), {"fields": ("email", "phone_number", "role")}),
        (_("Statutation & Validation"), {"fields": ("is_active", "is_verified", "is_staff", "is_admin", "is_superuser")}),
        (_("Données Techniques"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    readonly_fields = ("created_at", "updated_at")

    def full_name(self, obj):
        if hasattr(obj, "profile"):
            return f"{obj.profile.first_name} {obj.profile.last_name}"
        return "-"
    full_name.short_description = _("Nom complet")  # type: ignore[attr-defined]  # pattern Django admin standard : attribut dynamique sur méthode


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "role", "scope", "is_principal", "is_active", "created_at")
    list_filter = ("role", "scope", "is_active", "is_principal")
    search_fields = ("user__email", "note")
    raw_id_fields = ("user", "province", "diocese", "parish", "church", "granted_by")


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "church", "is_primary", "created_at")
    list_filter = ("is_primary",)
    search_fields = ("user__email", "church__name", "church__parish__name")
    raw_id_fields = ("user", "church")


@admin.register(ClergySelfDeclaration)
class ClergySelfDeclarationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "claimed_pastoral_role",
        "parish",
        "status",
        "reviewed_by",
        "created_at",
    )
    list_filter = ("status", "claimed_pastoral_role", "created_at")
    search_fields = ("user__email", "parish__name")
    raw_id_fields = ("user", "parish", "justification_file", "reviewed_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(SecurityAuditLog)
class SecurityAuditLogAdmin(admin.ModelAdmin):
    list_display = ("event", "user", "ip_address", "created_at")
    list_filter = ("event", "created_at")
    search_fields = ("user__email", "ip_address", "user_agent")
    readonly_fields = ("user", "event", "ip_address", "user_agent", "metadata", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if change:
            return super().save_model(request, obj, form, change)

        try:
            obj.full_clean()
            super().save_model(request, obj, form, change)
        except ValidationError as exc:
            self.message_user(request, str(exc), messages.ERROR)

