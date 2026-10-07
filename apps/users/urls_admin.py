from django.urls import path

from apps.users import apis_admin as a

urlpatterns = [
    path("scope/", a.AdminScopeApi.as_view(), name="scope"),
    path("dashboard/", a.AdminDashboardApi.as_view(), name="dashboard"),
    path("audit/", a.AdminAuditListApi.as_view(), name="audit"),
    path("sync/", a.AdminSyncStatusApi.as_view(), name="sync-status"),
    path("sync/runs/", a.AdminSyncRunCreateApi.as_view(), name="sync-run"),
    path("sync/runs/<int:run_id>/", a.AdminSyncRunDetailApi.as_view(), name="sync-run-detail"),
    path("accounts/", a.AdminAccountListCreateApi.as_view(), name="accounts"),
    path("accounts/export/", a.AdminAccountExportApi.as_view(), name="accounts-export"),
    path("accounts/<uuid:account_id>/", a.AdminAccountDetailApi.as_view(), name="account"),
    path("accounts/<uuid:account_id>/disable/", a.AdminAccountDisableApi.as_view(), name="account-disable"),
    path("accounts/<uuid:account_id>/enable/", a.AdminAccountEnableApi.as_view(), name="account-enable"),
    path(
        "accounts/<uuid:account_id>/password-reset/",
        a.AdminAccountPasswordResetApi.as_view(),
        name="account-password-reset",
    ),
    path(
        "accounts/<uuid:account_id>/actions-email/",
        a.AdminAccountActionsEmailApi.as_view(),
        name="account-actions-email",
    ),
    path(
        "accounts/<uuid:account_id>/verify-email/", a.AdminAccountVerifyEmailApi.as_view(), name="account-verify-email"
    ),
    path(
        "accounts/<uuid:account_id>/mark-email-verified/",
        a.AdminAccountMarkEmailVerifiedApi.as_view(),
        name="account-mark-email-verified",
    ),
    path("accounts/<uuid:account_id>/sessions/", a.AdminAccountSessionsApi.as_view(), name="account-sessions"),
    path(
        "accounts/<uuid:account_id>/sessions/<str:session_id>/",
        a.AdminAccountSessionRevokeApi.as_view(),
        name="account-session-revoke",
    ),
    path("accounts/<uuid:account_id>/logout/", a.AdminAccountLogoutApi.as_view(), name="account-logout"),
    path("accounts/<uuid:account_id>/otp-reset/", a.AdminAccountOtpResetApi.as_view(), name="account-otp-reset"),
    path(
        "accounts/<uuid:account_id>/brute-force-unlock/",
        a.AdminAccountBruteForceUnlockApi.as_view(),
        name="account-brute-force-unlock",
    ),
    path(
        "accounts/<uuid:account_id>/platform-admin/",
        a.AdminAccountPlatformAdminApi.as_view(),
        name="account-platform-admin",
    ),
    path("accounts/<uuid:account_id>/resync/", a.AdminAccountResyncApi.as_view(), name="account-resync"),
    path("accounts/<uuid:account_id>/offices/", a.AdminAccountOfficeAssignApi.as_view(), name="account-offices"),
    path(
        "accounts/<uuid:account_id>/offices/<int:assignment_id>/end/",
        a.AdminAccountOfficeEndApi.as_view(),
        name="account-office-end",
    ),
]
