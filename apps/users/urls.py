from django.urls import path

from .apis import (
    EmailChangeConfirmApi,
    EmailChangeRequestApi,
    EmailChangeRevertApi,
    EmailVerifyApi,
    EmailVerifyResendApi,
    FideleRegisterApi,
    PasswordChangeApi,
    PasswordResetConfirmApi,
    PasswordResetRequestApi,
    UserAdminCreateApi,
    UserAuditLogApi,
    UserDetailApi,
    UserHardDeleteApi,
    UserListApi,
    UserMeDeleteApi,
    UserMeDetailApi,
    UserMeUpdateApi,
    UserSoftDeleteApi,
    UserToggleActiveApi,
)
from .apis_clergy import (
    ClergyAccountRejectApi,
    ClergyAccountValidateApi,
    ClergyDeclarationMeApi,
    PendingClergyListApi,
)
from .apis_memberships import (
    MembershipMeDeleteApi,
    MembershipMeListCreateApi,
    MembershipMeSetPrimaryApi,
)
from .apis_roles import (
    RoleAssignmentListApi,
    RoleAssignmentRevokeApi,
)

urlpatterns = [
    # -------------------------------------------------------------------------
    # Inscription
    # -------------------------------------------------------------------------
    path("register/", FideleRegisterApi.as_view(), name="register"),
    path("verify-email/", EmailVerifyApi.as_view(), name="verify-email"),
    path("verify-email/resend/", EmailVerifyResendApi.as_view(), name="verify-email-resend"),

    # -------------------------------------------------------------------------
    # Mot de passe
    # -------------------------------------------------------------------------
    path("password/reset/request/", PasswordResetRequestApi.as_view(), name="password-reset-request"),
    path("password/reset/confirm/", PasswordResetConfirmApi.as_view(), name="password-reset-confirm"),
    path("password/change/", PasswordChangeApi.as_view(), name="password-change"),

    # -------------------------------------------------------------------------
    # Email
    # -------------------------------------------------------------------------
    path("email/change/request/", EmailChangeRequestApi.as_view(), name="email-change-request"),
    path("email/change/confirm/", EmailChangeConfirmApi.as_view(), name="email-change-confirm"),
    path("email/change/revert/", EmailChangeRevertApi.as_view(), name="email-change-revert"),

    # -------------------------------------------------------------------------
    # Profil (propriétaire)
    # -------------------------------------------------------------------------
    path("me/", UserMeDetailApi.as_view(), name="me-detail"),
    path("me/update/", UserMeUpdateApi.as_view(), name="me-update"),
    path("me/delete/", UserMeDeleteApi.as_view(), name="me-delete"),

    # Appartenances ecclésiales (multi-appartenance) — propriétaire uniquement
    # Auto-déclaration de clergé — la voie par laquelle un compte entre en file
    # d'attente (l'invitation, elle, naît déjà validée).
    path(
        "me/clergy-declaration/",
        ClergyDeclarationMeApi.as_view(),
        name="me-clergy-declaration",
    ),

    path(
        "me/memberships/",
        MembershipMeListCreateApi.as_view(),
        name="me-membership-list-create",
    ),
    path(
        "me/memberships/<int:membership_id>/",
        MembershipMeDeleteApi.as_view(),
        name="me-membership-delete",
    ),
    path(
        "me/memberships/<int:membership_id>/set-primary/",
        MembershipMeSetPrimaryApi.as_view(),
        name="me-membership-set-primary",
    ),

    # -------------------------------------------------------------------------
    # Administration
    # -------------------------------------------------------------------------
    path("", UserListApi.as_view(), name="list"),
    path("admin/create/", UserAdminCreateApi.as_view(), name="admin-create"),

    # Chaîne de validation des comptes clergé (auto-déclaration).
    # Le littéral doit précéder <uuid:user_id>/ pour ne pas être capturé par lui.
    path(
        "pending-validation/",
        PendingClergyListApi.as_view(),
        name="clergy-pending-validation",
    ),

    path("<uuid:user_id>/", UserDetailApi.as_view(), name="detail"),
    path(
        "<uuid:user_id>/validate-account/",
        ClergyAccountValidateApi.as_view(),
        name="clergy-validate-account",
    ),
    path(
        "<uuid:user_id>/reject-account/",
        ClergyAccountRejectApi.as_view(),
        name="clergy-reject-account",
    ),
    path("<uuid:user_id>/toggle-active/", UserToggleActiveApi.as_view(), name="toggle-active"),
    path("<uuid:user_id>/delete/", UserSoftDeleteApi.as_view(), name="soft-delete"),
    path("<uuid:user_id>/hard-delete/", UserHardDeleteApi.as_view(), name="hard-delete"),
    path("<uuid:user_id>/audit-logs/", UserAuditLogApi.as_view(), name="audit-logs"),

    # -------------------------------------------------------------------------
    # Affectations de rôle scopées (RBAC territorial)
    # -------------------------------------------------------------------------
    path("role-assignments/", RoleAssignmentListApi.as_view(), name="role-assignment-list"),
    path(
        "role-assignments/<int:assignment_id>/revoke/",
        RoleAssignmentRevokeApi.as_view(),
        name="role-assignment-revoke",
    ),
]
