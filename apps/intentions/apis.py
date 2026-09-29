"""Intentions de messe (lot V1-routes) : couche HTTP. Aucun montant, aucun paiement."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin, PermissionClassesType
from apps.api.pagination import LimitOffsetPagination, get_paginated_response, paginated_response_serializer
from apps.api.v1 import V1ApiMixin
from apps.hierarchy import selectors as hierarchy_selectors
from apps.hierarchy.authz import HasCapability
from apps.intentions import selectors, services
from apps.intentions.enums import OFFERING_NOTICE
from apps.intentions.serializers import (
    DeclineInputSerializer,
    IntentionCreateInputSerializer,
    MassIntentionOutputSerializer,
    NoticeOutputSerializer,
    ParishFilterSerializer,
    ScheduleInputSerializer,
    StaffMassIntentionOutputSerializer,
)

TAG = ["intentions"]
_PAGINATION = [
    OpenApiParameter("limit", int, description="Nombre de résultats (défaut 10, max 50)"),
    OpenApiParameter("offset", int, description="Décalage"),
]


class _AuthedApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes: PermissionClassesType = (IsAuthenticated,)


class _StaffApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes: PermissionClassesType = (IsAuthenticated, HasCapability("intentions.gerer"))


def _place(place_id: int | None):  # noqa: ANN202
    return hierarchy_selectors.place_get(place_id=place_id) if place_id else None


class NoticeApi(V1ApiMixin, APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    @extend_schema(
        tags=TAG,
        operation_id="mass_intentions_notice",
        summary="Texte informatif : l'offrande de messe se remet à la paroisse (jamais dans l'application)",
        responses=NoticeOutputSerializer,
    )
    def get(self, request: Request) -> Response:
        return Response({"notice": OFFERING_NOTICE})


class IntentionCreateApi(_AuthedApi):
    @extend_schema(
        tags=TAG,
        operation_id="mass_intentions_create",
        summary="Demander une intention de messe à une paroisse (sans offrande dans l'application)",
        request=IntentionCreateInputSerializer,
        responses={201: MassIntentionOutputSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = IntentionCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        node = hierarchy_selectors.node_get(node_id=data.pop("node"))
        place = _place(data.pop("place_id"))
        obj = services.intention_create(requester=request.user, node=node, place=place, **data)
        return Response(
            MassIntentionOutputSerializer(selectors.intention_get_for_person(user=request.user, intention_id=obj.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class MyIntentionsApi(_AuthedApi):
    @extend_schema(
        tags=TAG,
        operation_id="mass_intentions_mine",
        summary="Mes intentions de messe",
        parameters=_PAGINATION,
        responses=paginated_response_serializer(MassIntentionOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=MassIntentionOutputSerializer,
            queryset=selectors.intentions_for_person(user=request.user),
            request=request,
            view=self,
        )


class IntentionCancelApi(_AuthedApi):
    @extend_schema(
        tags=TAG,
        operation_id="mass_intentions_cancel",
        summary="Annuler mon intention (reçue ou planifiée)",
        request=None,
        responses=MassIntentionOutputSerializer,
    )
    def post(self, request: Request, intention_id: str) -> Response:
        obj = selectors.intention_get_for_person(user=request.user, intention_id=intention_id)
        services.intention_cancel(intention=obj, requester=request.user)
        return Response(
            MassIntentionOutputSerializer(selectors.intention_get_for_person(user=request.user, intention_id=obj.pk)).data
        )


class ParishIntentionsApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        operation_id="mass_intentions_parish",
        summary="Intentions reçues par une paroisse (secrétariat)",
        parameters=[ParishFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(StaffMassIntentionOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = ParishFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        data = dict(filters.validated_data)
        node = hierarchy_selectors.node_get(node_id=data.pop("node"))
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=StaffMassIntentionOutputSerializer,
            queryset=selectors.intentions_for_parish(user=request.user, node=node, **data),
            request=request,
            view=self,
        )


def _staff_response(request: Request, intention_id: str) -> Response:
    obj = selectors.intention_get_for_staff(user=request.user, intention_id=intention_id)
    return Response(StaffMassIntentionOutputSerializer(obj).data)


class IntentionAcceptApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        operation_id="mass_intentions_accept",
        summary="Planifier (ou déplacer) une intention à une messe ; le fidèle est prévenu",
        request=ScheduleInputSerializer,
        responses=StaffMassIntentionOutputSerializer,
    )
    def post(self, request: Request, intention_id: str) -> Response:
        serializer = ScheduleInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        obj = selectors.intention_get_for_staff(user=request.user, intention_id=intention_id)
        services.intention_schedule(intention=obj, actor=request.user, place=_place(data.pop("place_id")), **data)
        return _staff_response(request, intention_id)


class IntentionDeclineApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        operation_id="mass_intentions_decline",
        summary="Refuser une intention avec un motif ; le fidèle est prévenu",
        request=DeclineInputSerializer,
        responses=StaffMassIntentionOutputSerializer,
    )
    def post(self, request: Request, intention_id: str) -> Response:
        serializer = DeclineInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj = selectors.intention_get_for_staff(user=request.user, intention_id=intention_id)
        services.intention_decline(intention=obj, actor=request.user, reason=serializer.validated_data["reason"])
        return _staff_response(request, intention_id)


class IntentionCelebrateApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        operation_id="mass_intentions_celebrate",
        summary="Marquer une intention planifiée comme célébrée",
        request=None,
        responses=StaffMassIntentionOutputSerializer,
    )
    def post(self, request: Request, intention_id: str) -> Response:
        obj = selectors.intention_get_for_staff(user=request.user, intention_id=intention_id)
        services.intention_celebrate(intention=obj, actor=request.user)
        return _staff_response(request, intention_id)
