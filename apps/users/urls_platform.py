from django.urls import path

from apps.users import apis_accounts

urlpatterns = [
    path("", apis_accounts.AccountListApi.as_view(), name="list"),
    path("<uuid:account_id>/", apis_accounts.AccountDetailApi.as_view(), name="detail"),
    path("<uuid:account_id>/lock/", apis_accounts.AccountLockApi.as_view(), name="lock"),
    path("<uuid:account_id>/unlock/", apis_accounts.AccountUnlockApi.as_view(), name="unlock"),
    path(
        "<uuid:account_id>/logout-sessions/", apis_accounts.AccountLogoutSessionsApi.as_view(), name="logout-sessions"
    ),
    path("<uuid:account_id>/require-mfa/", apis_accounts.AccountRequireMfaApi.as_view(), name="require-mfa"),
]
