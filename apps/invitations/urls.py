from django.urls import path

from apps.invitations import apis

urlpatterns = [
    path("invitations/", apis.InvitationListCreateApi.as_view(), name="invitations"),
    path("invitations/validate/", apis.InvitationValidateApi.as_view(), name="invitation-validate"),
    path("invitations/accept/", apis.InvitationAcceptApi.as_view(), name="invitation-accept"),
    path("invitations/<uuid:invitation_id>/revoke/", apis.InvitationRevokeApi.as_view(), name="invitation-revoke"),
    path("", apis.AccountListApi.as_view(), name="accounts"),
    path("validated/", apis.ValidatedAccountsApi.as_view(), name="validated"),
    path("pending/", apis.PendingAccountsApi.as_view(), name="pending"),
    path("<uuid:person_id>/validate/", apis.AccountValidateApi.as_view(), name="account-validate"),
    path("<uuid:person_id>/refuse/", apis.AccountRefuseApi.as_view(), name="account-refuse"),
    path("<uuid:person_id>/activate/", apis.AccountActivateApi.as_view(), name="account-activate"),
    path("<uuid:person_id>/deactivate/", apis.AccountDeactivateApi.as_view(), name="account-deactivate"),
]
