"""Comptes plateforme (SRS §2 : ``plateforme.admin`` administre les comptes ; MFA exigée)."""

from collections.abc import Callable
from typing import Any

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin
from apps.api.pagination import LimitOffsetPagination, paginated_response_serializer
from apps.api.v1 import V1ApiMixin
from apps.hierarchy.authz import HasCapability
from apps.users import selectors_accounts, services_accounts
from apps.users.keycloak_accounts import MFA_NONE, MFA_TOTP, MFA_WEBAUTHN, keycloak_directory

TAG = ["platform"]
_PAGINATION = [
    OpenApiParameter("limit", int, description="Nombre de résultats (défaut 10, max 50)"),
    OpenApiParameter("offset", int, description="Décalage"),
]
MFA_CHOICES = (MFA_TOTP, MFA_WEBAUTHN, MFA_NONE)


class AccountFilterSerializer(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True, max_length=100, help_text="E-mail, prénom ou nom")
    role = serializers.ChoiceField(choices=selectors_accounts.ROLES, required=False, help_text="Rôle de realm")
    mfa = serializers.ChoiceField(choices=selectors_accounts.MFA_FILTERS, required=False, help_text="MFA configurée ou non")
    status = serializers.ChoiceField(choices=selectors_accounts.STATUSES, required=False, help_text="Statut du compte")


class AccountOutputSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    full_name = serializers.CharField()
    realm_role = serializers.ChoiceField(choices=selectors_accounts.ROLES)
    mfa = serializers.ChoiceField(choices=MFA_CHOICES)
    last_login = serializers.DateTimeField(allow_null=True, help_text="Dernière activité connue")
    status = serializers.ChoiceField(choices=selectors_accounts.STATUSES)
    node_label = serializers.CharField(allow_null=True, help_text="Nœud de la nomination principale, ou paroisse suivie")


class AccountOfficeSerializer(serializers.Serializer):
    office_label = serializers.CharField()
    node_name = serializers.CharField()
    start_date = serializers.DateField()
    capabilities = serializers.ListField(child=serializers.CharField())


class AccountSessionSerializer(serializers.Serializer):
    id = serializers.CharField()
    client = serializers.CharField()
    ip = serializers.CharField(allow_null=True)
    started_at = serializers.DateTimeField(allow_null=True)


class AccountDetailOutputSerializer(AccountOutputSerializer):
    keycloak_id = serializers.CharField(allow_null=True)
    email_verified = serializers.BooleanField()
    offices = AccountOfficeSerializer(many=True)
    sessions = AccountSessionSerializer(many=True)


def _ip(request: Request) -> str | None:
    return request.META.get("REMOTE_ADDR")


class _PlatformApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated, HasCapability("plateforme.admin"))


class AccountListApi(_PlatformApi):
    @extend_schema(
        tags=TAG,
        operation_id="platform_accounts_list",
        summary="Comptes de la plateforme, du plus récemment actif au plus ancien",
        parameters=[AccountFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(AccountOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = AccountFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        directory = keycloak_directory()
        paginator = LimitOffsetPagination()
        page = paginator.paginate_queryset(
            selectors_accounts.account_list(filters=filters.validated_data, directory=directory), request, view=self
        )
        rows = [selectors_accounts.account_row(user=user, directory=directory) for user in page or []]
        return paginator.get_paginated_response(AccountOutputSerializer(rows, many=True).data)


class AccountDetailApi(_PlatformApi):
    @extend_schema(
        tags=TAG,
        operation_id="platform_accounts_retrieve",
        summary="Fiche d'un compte : MFA, sessions, offices",
        responses=AccountDetailOutputSerializer,
    )
    def get(self, request: Request, account_id: str) -> Response:
        account = selectors_accounts.account_get(account_id=account_id)
        return Response(AccountDetailOutputSerializer(selectors_accounts.account_detail(user=account)).data)


def _action_view(
    *, service: Callable[..., Any], operation_id: str, summary: str
) -> type[_PlatformApi]:
    class _AccountActionApi(_PlatformApi):
        @extend_schema(
            tags=TAG,
            operation_id=operation_id,
            summary=summary,
            request=None,
            responses={
                200: AccountDetailOutputSerializer,
                503: OpenApiResponse(description="Keycloak injoignable : action non effectuée"),
            },
        )
        def post(self, request: Request, account_id: str) -> Response:
            account = selectors_accounts.account_get(account_id=account_id)
            service(account=account, actor=request.user, ip=_ip(request))
            refreshed = selectors_accounts.account_get(account_id=account_id)
            return Response(AccountDetailOutputSerializer(selectors_accounts.account_detail(user=refreshed)).data)

    _AccountActionApi.__name__ = "".join(part.title() for part in operation_id.split("_")) + "Api"
    return _AccountActionApi


AccountLockApi = _action_view(
    service=services_accounts.account_lock,
    operation_id="platform_accounts_lock",
    summary="Verrouiller un compte (désactivé dans Keycloak, sessions fermées)",
)
AccountUnlockApi = _action_view(
    service=services_accounts.account_unlock,
    operation_id="platform_accounts_unlock",
    summary="Déverrouiller un compte",
)
AccountLogoutSessionsApi = _action_view(
    service=services_accounts.account_logout_sessions,
    operation_id="platform_accounts_logout_sessions",
    summary="Fermer toutes les sessions d'un compte",
)
AccountRequireMfaApi = _action_view(
    service=services_accounts.account_require_mfa,
    operation_id="platform_accounts_require_mfa",
    summary="Exiger la configuration d'un second facteur à la prochaine connexion",
)
