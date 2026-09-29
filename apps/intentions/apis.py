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
from apps.core.exceptions import PermissionDeniedError
from apps.hierarchy import authz
from apps.hierarchy import selectors as hierarchy_selectors
from apps.hierarchy.authz import HasCapability
from apps.intentions import selectors, services
from apps.intentions.enums import OFFERING_NOTICE
from apps.intentions.serializers import (
    DayFilterSerializer,
    DayMassesOutputSerializer,
    DeclineInputSerializer,
    IntentionCreateInputSerializer,
    MassCapInputSerializer,
    MassCapKeySerializer,
    MassCapOutputSerializer,
    MassIntentionOutputSerializer,
    NoticeOutputSerializer,
    ParishFilterSerializer,
    ScheduleInputSerializer,
    SettingsFilterSerializer,
    SettingsInputSerializer,
    SettingsOutputSerializer,
    SheetOutputSerializer,
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
            MassIntentionOutputSerializer(
                selectors.intention_get_for_person(user=request.user, intention_id=obj.pk)
            ).data,
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
            MassIntentionOutputSerializer(
                selectors.intention_get_for_person(user=request.user, intention_id=obj.pk)
            ).data
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


def _day(request: Request):  # noqa: ANN202
    filters = DayFilterSerializer(data=request.query_params)
    filters.is_valid(raise_exception=True)
    return hierarchy_selectors.node_get(node_id=filters.validated_data["node"]), filters.validated_data["date"]


class ParishMassesApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        operation_id="mass_intentions_parish_masses",
        summary="Messes d'un jour (horaires des lieux) avec nombre d'intentions retenues et plafond",
        parameters=[DayFilterSerializer],
        responses=DayMassesOutputSerializer,
    )
    def get(self, request: Request) -> Response:
        node, day = _day(request)
        return Response(
            DayMassesOutputSerializer(selectors.parish_masses_of_day(user=request.user, node=node, day=day)).data
        )


class ParishSheetApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        operation_id="mass_intentions_parish_sheet",
        summary="Feuille imprimable des intentions d'un jour, par messe (texte des intentions, sans montant)",
        parameters=[DayFilterSerializer],
        responses=SheetOutputSerializer,
    )
    def get(self, request: Request) -> Response:
        node, day = _day(request)
        return Response(SheetOutputSerializer(selectors.parish_sheet(user=request.user, node=node, day=day)).data)


class ParishSettingsApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        operation_id="mass_intentions_settings_get",
        summary="Réglages des intentions d'une paroisse (plafond par messe, 5 par défaut)",
        parameters=[SettingsFilterSerializer],
        responses=SettingsOutputSerializer,
    )
    def get(self, request: Request) -> Response:
        filters = SettingsFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        node = hierarchy_selectors.node_get(node_id=filters.validated_data["node"])
        if not authz.peut(request.user, "intentions.gerer", node):
            raise PermissionDeniedError(
                "Vous ne gérez pas les intentions de cette paroisse.", code="intentions_forbidden"
            )
        return Response({"node": str(node.pk), "max_per_mass": services.max_per_mass(node=node)})

    @extend_schema(
        tags=TAG,
        operation_id="mass_intentions_settings_update",
        summary="Changer le plafond d'intentions par messe (1 à 50, null = sans plafond)",
        request=SettingsInputSerializer,
        responses=SettingsOutputSerializer,
    )
    def patch(self, request: Request) -> Response:
        serializer = SettingsInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        node = hierarchy_selectors.node_get(node_id=serializer.validated_data["node"])
        obj = services.intention_settings_update(
            node=node, actor=request.user, max_per_mass=serializer.validated_data["max_per_mass"]
        )
        return Response({"node": str(node.pk), "max_per_mass": obj.max_per_mass})


def _cap_key(data: dict) -> dict:
    node = hierarchy_selectors.node_get(node_id=data["node"])
    return {
        "node": node,
        "place": hierarchy_selectors.place_get(place_id=data["place_id"]),
        "start_time": data["start_time"],
        "weekday": data.get("weekday"),
        "date": data.get("date"),
    }


class MassCapApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        operation_id="mass_intentions_mass_caps_list",
        summary="Plafonds propres aux messes d'une paroisse (horaires et messes datées)",
        parameters=[SettingsFilterSerializer],
        responses=MassCapOutputSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        filters = SettingsFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        node = hierarchy_selectors.node_get(node_id=filters.validated_data["node"])
        return Response(MassCapOutputSerializer(selectors.mass_caps(user=request.user, node=node), many=True).data)

    @extend_schema(
        tags=TAG,
        operation_id="mass_intentions_mass_cap_set",
        summary="Fixer le plafond d'une messe (1 à 50, null = sans plafond)",
        request=MassCapInputSerializer,
        responses=MassCapOutputSerializer,
    )
    def put(self, request: Request) -> Response:
        serializer = MassCapInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj = services.mass_cap_set(
            actor=request.user,
            max_intentions=serializer.validated_data["max_intentions"],
            **_cap_key(serializer.validated_data),
        )
        return Response(MassCapOutputSerializer(obj).data)

    @extend_schema(
        tags=TAG,
        operation_id="mass_intentions_mass_cap_clear",
        summary="Retirer le plafond propre à une messe (le réglage de la paroisse s'applique)",
        parameters=[MassCapKeySerializer],
        responses={204: None},
    )
    def delete(self, request: Request) -> Response:
        serializer = MassCapKeySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        services.mass_cap_clear(actor=request.user, **_cap_key(serializer.validated_data))
        return Response(status=status.HTTP_204_NO_CONTENT)
