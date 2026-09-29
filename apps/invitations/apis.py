"""Invitations et validation des comptes du clergé (lot V1-routes) : couche HTTP."""

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin, PermissionClassesType
from apps.api.pagination import LimitOffsetPagination, get_paginated_response, paginated_response_serializer
from apps.api.v1 import V1ApiMixin
from apps.core.request_context import client_ip
from apps.hierarchy import selectors as hierarchy_selectors
from apps.hierarchy.authz import HasCapability
from apps.invitations import selectors, services
from apps.invitations.serializers import (
    AcceptInputSerializer,
    AccountFilterSerializer,
    ClergyAccountOutputSerializer,
    InvitationCreateInputSerializer,
    InvitationCreatedOutputSerializer,
    InvitationFilterSerializer,
    InvitationOutputSerializer,
    InvitationPublicOutputSerializer,
    PendingFilterSerializer,
    RefuseInputSerializer,
    TokenInputSerializer,
    invitation_public_payload,
)

TAG = ["clergy-accounts"]
_PAGINATION = [
    OpenApiParameter("limit", int, description="Nombre de résultats (défaut 10, max 50)"),
    OpenApiParameter("offset", int, description="Décalage"),
]
_GONE = OpenApiResponse(description="410 invitation_invalide / invitation_expiree")


class _ManagerApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes: PermissionClassesType = (IsAuthenticated, HasCapability("comptes.valider"))


class InvitationListCreateApi(_ManagerApi):
    @extend_schema(
        tags=TAG,
        operation_id="clergy_invitations_list",
        summary="Invitations de mes nœuds (en attente, acceptées, révoquées, expirées)",
        parameters=[InvitationFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(InvitationOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = InvitationFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=InvitationOutputSerializer,
            queryset=selectors.invitation_list(user=request.user, filters=filters.validated_data),
            request=request,
            view=self,
        )

    @extend_schema(
        tags=TAG,
        operation_id="clergy_invitations_create",
        summary="Inviter un clerc ou un consacré (lien envoyé par e-mail, expiration)",
        request=InvitationCreateInputSerializer,
        responses={201: InvitationCreatedOutputSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = InvitationCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        node = hierarchy_selectors.node_get(node_id=data.pop("node"))
        invitation, token = services.invitation_create(actor=request.user, node=node, **data)
        invitation = selectors.invitation_get(user=request.user, invitation_id=invitation.pk)
        invitation.accept_url = services.accept_url(token)  # type: ignore[attr-defined]
        return Response(InvitationCreatedOutputSerializer(invitation).data, status=status.HTTP_201_CREATED)


class InvitationRevokeApi(_ManagerApi):
    @extend_schema(
        tags=TAG,
        operation_id="clergy_invitations_revoke",
        summary="Révoquer une invitation en attente",
        request=None,
        responses=InvitationOutputSerializer,
    )
    def post(self, request: Request, invitation_id: str) -> Response:
        invitation = selectors.invitation_get(user=request.user, invitation_id=invitation_id)
        services.invitation_revoke(actor=request.user, invitation=invitation)
        return Response(
            InvitationOutputSerializer(selectors.invitation_get(user=request.user, invitation_id=invitation_id)).data
        )


class InvitationValidateApi(V1ApiMixin, APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    @extend_schema(
        tags=TAG,
        operation_id="clergy_invitations_validate",
        summary="Vérifier un lien d'invitation (public) : nœud, adresse masquée, lien d'inscription Keycloak",
        request=TokenInputSerializer,
        responses={200: InvitationPublicOutputSerializer, 410: _GONE},
    )
    def post(self, request: Request) -> Response:
        serializer = TokenInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["token"]
        invitation = services.invitation_from_token(token=token)
        return Response(InvitationPublicOutputSerializer(invitation_public_payload(invitation=invitation, token=token)).data)


class InvitationAcceptApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes: PermissionClassesType = (IsAuthenticated,)

    @extend_schema(
        tags=TAG,
        operation_id="clergy_invitations_accept",
        summary="Accepter l'invitation (connecté par Keycloak avec l'adresse invitée) : compte en attente",
        request=AcceptInputSerializer,
        responses={200: ClergyAccountOutputSerializer, 410: _GONE},
    )
    def post(self, request: Request) -> Response:
        serializer = AcceptInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = services.invitation_accept(
            token=serializer.validated_data["token"],
            user=request.user,
            justificatif_id=serializer.validated_data["justificatif_id"],
        )
        person = selectors.account_get(user=None, person_id=invitation.accepted_by_id, scoped=False)
        return Response(ClergyAccountOutputSerializer(person).data)


class PendingAccountsApi(_ManagerApi):
    @extend_schema(
        tags=TAG,
        operation_id="clergy_accounts_pending",
        summary="Comptes du clergé en attente de validation",
        parameters=[PendingFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(ClergyAccountOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = PendingFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=ClergyAccountOutputSerializer,
            queryset=selectors.pending_accounts(user=request.user, filters=filters.validated_data),
            request=request,
            view=self,
        )


class AccountListApi(_ManagerApi):
    @extend_schema(
        tags=TAG,
        operation_id="clergy_accounts_list",
        summary="Comptes du clergé invités dans mon périmètre (filtres diocèse, rôle, statut)",
        parameters=[AccountFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(ClergyAccountOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = AccountFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=ClergyAccountOutputSerializer,
            queryset=selectors.accounts_list(user=request.user, filters=filters.validated_data),
            request=request,
            view=self,
        )


class ValidatedAccountsApi(_ManagerApi):
    @extend_schema(
        tags=TAG,
        operation_id="clergy_accounts_validated",
        summary="Comptes du clergé validés (filtres diocèse, rôle)",
        parameters=[PendingFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(ClergyAccountOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = PendingFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=ClergyAccountOutputSerializer,
            queryset=selectors.accounts_list(user=request.user, filters={**filters.validated_data, "statut": "verifie"}),
            request=request,
            view=self,
        )


class AccountValidateApi(_ManagerApi):
    @extend_schema(
        tags=TAG,
        operation_id="clergy_accounts_validate",
        summary="Valider un compte en attente",
        request=None,
        responses=ClergyAccountOutputSerializer,
    )
    def post(self, request: Request, person_id: str) -> Response:
        person = selectors.account_get(user=request.user, person_id=person_id)
        person = services.account_decide(actor=request.user, person=person, approve=True)
        return Response(ClergyAccountOutputSerializer(person).data)


class AccountRefuseApi(_ManagerApi):
    @extend_schema(
        tags=TAG,
        operation_id="clergy_accounts_refuse",
        summary="Refuser un compte en attente (motif obligatoire)",
        request=RefuseInputSerializer,
        responses=ClergyAccountOutputSerializer,
    )
    def post(self, request: Request, person_id: str) -> Response:
        serializer = RefuseInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        person = selectors.account_get(user=request.user, person_id=person_id)
        person = services.account_decide(
            actor=request.user, person=person, approve=False, reason=serializer.validated_data["reason"]
        )
        return Response(ClergyAccountOutputSerializer(person).data)


def _activation_view(*, active: bool, operation_id: str, summary: str) -> type[_ManagerApi]:
    class _Api(_ManagerApi):
        @extend_schema(
            tags=TAG,
            operation_id=operation_id,
            summary=summary,
            request=None,
            responses={200: ClergyAccountOutputSerializer, 503: OpenApiResponse(description="Keycloak injoignable")},
        )
        def post(self, request: Request, person_id: str) -> Response:
            person = selectors.account_get(user=request.user, person_id=person_id)
            person = services.account_set_active(
                actor=request.user, person=person, active=active, ip=client_ip(request.META)
            )
            return Response(ClergyAccountOutputSerializer(person).data)

    _Api.__name__ = "".join(part.title() for part in operation_id.split("_")) + "Api"
    return _Api


AccountActivateApi = _activation_view(
    active=True, operation_id="clergy_accounts_activate", summary="Activer un compte du clergé (Keycloak)"
)
AccountDeactivateApi = _activation_view(
    active=False,
    operation_id="clergy_accounts_deactivate",
    summary="Désactiver un compte du clergé (Keycloak, sessions fermées)",
)
