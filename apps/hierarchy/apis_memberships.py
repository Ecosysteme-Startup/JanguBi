"""Paroisses multiples (décisions 6-8 du 29/09/2026) : couche HTTP.

- côté fidèle, sous ``/api/v1/me/paroisses/`` : adhésion libre, une principale, des secondaires ;
- côté paroisse, sous ``/api/v1/hierarchy/nodes/<id>/membres/`` : ``paroissiens.gerer``.
"""

from typing import Any

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.api.pagination import LimitOffsetPagination, get_paginated_response, paginated_response_serializer
from apps.hierarchy import selectors, selectors_memberships, services_memberships
from apps.hierarchy.apis_offices import ME_TAG, TAG, _PAGINATION, AuthedV1Api, _StaffMfa
from apps.hierarchy.authz import HasCapability, node_from_kwarg
from apps.hierarchy.serializers import NodeRefSerializer
from apps.users.models import BaseUser


class MaParoisseSerializer(serializers.Serializer):
    paroisse = NodeRefSerializer(source="node")
    principale = serializers.BooleanField(source="is_primary")
    membre_depuis = serializers.DateTimeField(source="joined_at", allow_null=True)


class MaParoisseInputSerializer(serializers.Serializer):
    paroisse_id = serializers.UUIDField()
    principale = serializers.BooleanField(
        required=False, default=False, help_text="En faire la paroisse principale (la première l'est d'office)"
    )


class MembreSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(source="user.pk")
    first_name = serializers.SerializerMethodField()
    last_name = serializers.SerializerMethodField()
    principale = serializers.BooleanField(source="is_primary", help_text="Cette paroisse est sa paroisse principale")
    membre_depuis = serializers.DateTimeField(source="joined_at")
    retire_le = serializers.DateTimeField(source="removed_by_parish_at", allow_null=True)

    def get_first_name(self, obj: Any) -> str:
        return getattr(getattr(obj.user, "profile", None), "first_name", "")

    def get_last_name(self, obj: Any) -> str:
        return getattr(getattr(obj.user, "profile", None), "last_name", "")


class MembresFilterSerializer(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True, default="")
    retires = serializers.BooleanField(required=False, default=False, help_text="Inclure les membres retirés")


def _mes_paroisses(user: Any) -> Any:
    return MaParoisseSerializer(selectors_memberships.memberships_of(user=user), many=True).data


class MesParoissesApi(AuthedV1Api):
    @extend_schema(
        tags=ME_TAG,
        operation_id="me_paroisses_list",
        summary="Mes paroisses : la principale d'abord, puis les secondaires",
        responses=MaParoisseSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        return Response(_mes_paroisses(request.user))

    @extend_schema(
        tags=ME_TAG,
        operation_id="me_paroisses_add",
        summary="Ajouter une paroisse (adhésion libre, idempotent)",
        request=MaParoisseInputSerializer,
        responses={
            201: MaParoisseSerializer(many=True),
            400: OpenApiResponse(description="not_a_parish, parish_deleted"),
            403: OpenApiResponse(description="retire_par_la_paroisse"),
        },
    )
    def post(self, request: Request) -> Response:
        serializer = MaParoisseInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        node = selectors.node_get(node_id=serializer.validated_data["paroisse_id"])
        services_memberships.membership_join(
            user=request.user, node=node, primary=serializer.validated_data["principale"]
        )
        return Response(_mes_paroisses(request.user), status=status.HTTP_201_CREATED)


class MaParoisseApi(AuthedV1Api):
    @extend_schema(
        tags=ME_TAG,
        operation_id="me_paroisses_remove",
        summary="Retirer une de mes paroisses (la plus ancienne secondaire remplace la principale)",
        responses={204: None, 404: OpenApiResponse(description="membre_introuvable")},
    )
    def delete(self, request: Request, node_id: str) -> Response:
        node = selectors.node_get(node_id=node_id)
        services_memberships.membership_leave(user=request.user, node=node)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MaParoissePrincipaleApi(AuthedV1Api):
    @extend_schema(
        tags=ME_TAG,
        operation_id="me_paroisses_set_primary",
        summary="En faire ma paroisse principale (une seule ; l'ancienne devient secondaire)",
        request=None,
        responses={200: MaParoisseSerializer(many=True), 404: OpenApiResponse(description="membre_introuvable")},
    )
    def put(self, request: Request, node_id: str) -> Response:
        node = selectors.node_get(node_id=node_id)
        services_memberships.membership_set_primary(user=request.user, node=node)
        return Response(_mes_paroisses(request.user))


# --- Côté paroisse -----------------------------------------------------------------------------


class _MembresApi(AuthedV1Api):
    permission_classes = (
        IsAuthenticated,
        _StaffMfa,
        HasCapability("paroissiens.gerer", node_resolver=node_from_kwarg("node_id")),
    )


def _member(user_id: str) -> BaseUser:
    user = BaseUser.objects.filter(pk=user_id).first()
    if user is None:
        from apps.core.exceptions import NotFoundError

        raise NotFoundError("Cette personne n'est pas membre de la paroisse.", code="membre_introuvable")
    return user


class MembresListApi(_MembresApi):
    @extend_schema(
        tags=TAG,
        operation_id="hierarchy_membres_list",
        summary="Membres de la paroisse (paroissiens.gerer), les plus récents d'abord",
        parameters=[
            OpenApiParameter("q", str, description="Nom ou e-mail"),
            OpenApiParameter("retires", bool, description="Inclure les membres retirés par la paroisse"),
            *_PAGINATION,
        ],
        responses=paginated_response_serializer(MembreSerializer),
    )
    def get(self, request: Request, node_id: str) -> Response:
        filters = MembresFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        node = selectors.node_get(node_id=node_id)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=MembreSerializer,
            queryset=selectors_memberships.members_of(
                node=node, include_removed=filters.validated_data["retires"], q=filters.validated_data["q"]
            ),
            request=request,
            view=self,
        )


class MembreRemoveApi(_MembresApi):
    @extend_schema(
        tags=TAG,
        operation_id="hierarchy_membres_remove",
        summary="Retirer un membre de la paroisse (il ne peut plus s'y réinscrire seul)",
        responses={204: None, 404: OpenApiResponse(description="membre_introuvable")},
    )
    def delete(self, request: Request, node_id: str, user_id: str) -> Response:
        node = selectors.node_get(node_id=node_id)
        services_memberships.membership_remove_by_parish(actor=request.user, node=node, user=_member(user_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class MembreRestoreApi(_MembresApi):
    @extend_schema(
        tags=TAG,
        operation_id="hierarchy_membres_restore",
        summary="Rétablir un membre retiré",
        request=None,
        responses={200: MembreSerializer, 404: OpenApiResponse(description="membre_introuvable")},
    )
    def post(self, request: Request, node_id: str, user_id: str) -> Response:
        node = selectors.node_get(node_id=node_id)
        membership = services_memberships.membership_restore_by_parish(
            actor=request.user, node=node, user=_member(user_id)
        )
        return Response(MembreSerializer(membership).data)
