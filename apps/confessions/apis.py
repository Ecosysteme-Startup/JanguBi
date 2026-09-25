from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin, PermissionClassesType
from apps.api.pagination import LimitOffsetPagination, get_paginated_response, paginated_response_serializer
from apps.api.v1 import V1ApiMixin
from apps.confessions import selectors, services
from apps.confessions.serializers import (
    AttendanceInputSerializer,
    BookingCreateInputSerializer,
    BookingOutputSerializer,
    PlanningFilterSerializer,
    PlanningSlotSerializer,
    RuleCreateInputSerializer,
    RuleOutputSerializer,
    SlotCancelInputSerializer,
    SlotFilterSerializer,
    SlotOutputSerializer,
)
from apps.hierarchy import selectors as hierarchy_selectors
from apps.hierarchy.authz import HasAnyCapability, HasCapability

TAG = ["confessions"]
_PAGINATION = [
    OpenApiParameter("limit", int, description="Nombre de résultats (défaut 10, max 50)"),
    OpenApiParameter("offset", int, description="Décalage"),
]


class _AuthedApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes: PermissionClassesType = (IsAuthenticated,)


class _PriestApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes: PermissionClassesType = (IsAuthenticated, HasCapability("confessions.gerer"))


# --- Fidèle -------------------------------------------------------------------------------


class SlotListApi(_AuthedApi):
    @extend_schema(
        tags=TAG,
        summary="Créneaux libres d'une paroisse ou d'un lieu",
        parameters=[SlotFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(SlotOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = SlotFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        data = filters.validated_data
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=SlotOutputSerializer,
            queryset=selectors.slots_available(
                node_id=data.get("node"), place_id=data.get("place"), date_from=data.get("date_from")
            ),
            request=request,
            view=self,
        )


class BookingCreateApi(_AuthedApi):
    @extend_schema(
        tags=TAG,
        summary="Réserver un créneau (409 s'il vient d'être pris)",
        request=BookingCreateInputSerializer,
        responses={201: BookingOutputSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = BookingCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        slot = selectors.slot_get_free(slot_id=serializer.validated_data["slot_id"])
        booking = services.booking_create(slot=slot, person=request.user)
        obj = selectors.booking_get_for_person(user=request.user, booking_id=booking.pk)
        return Response(BookingOutputSerializer(obj).data, status=status.HTTP_201_CREATED)


class BookingCancelApi(_AuthedApi):
    @extend_schema(
        tags=TAG, summary="Annuler mon rendez-vous (jusqu'à H-1)", request=None, responses=BookingOutputSerializer
    )
    def post(self, request: Request, booking_id: int) -> Response:
        booking = selectors.booking_get_for_person(user=request.user, booking_id=booking_id)
        services.booking_cancel_by_person(booking=booking, person=request.user)
        return Response(
            BookingOutputSerializer(selectors.booking_get_for_person(user=request.user, booking_id=booking_id)).data
        )


class MyBookingsApi(_AuthedApi):
    @extend_schema(
        tags=TAG,
        operation_id="me_confession_bookings_list",
        summary="Mes rendez-vous de confession",
        parameters=_PAGINATION,
        responses=paginated_response_serializer(BookingOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=BookingOutputSerializer,
            queryset=selectors.bookings_for_person(user=request.user),
            request=request,
            view=self,
        )


# --- Prêtre et secrétariat ----------------------------------------------------------------


class RuleListCreateApi(_PriestApi):
    @extend_schema(
        tags=TAG,
        operation_id="staff_confessions_rules_list",
        summary="Mes règles de créneaux",
        responses=RuleOutputSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        return Response(RuleOutputSerializer(selectors.rules_for_priest(user=request.user), many=True).data)

    @extend_schema(
        tags=TAG,
        summary="Créer une règle récurrente (génère 4 semaines de créneaux)",
        request=RuleCreateInputSerializer,
        responses={201: RuleOutputSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = RuleCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        place = hierarchy_selectors.place_get(place_id=data.pop("place_id"))
        rule = services.rule_create(priest=request.user, place=place, **data)
        return Response(RuleOutputSerializer(rule).data, status=status.HTTP_201_CREATED)


class RuleDetailApi(_PriestApi):
    @extend_schema(tags=TAG, summary="Désactiver une règle (les réservations restent)", responses={204: None})
    def delete(self, request: Request, rule_id: int) -> Response:
        rule = selectors.rule_get_for_priest(user=request.user, rule_id=rule_id)
        services.rule_deactivate(rule=rule, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlanningApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated, HasAnyCapability("confessions.gerer", "confessions.voir_planning"))

    @extend_schema(
        tags=TAG,
        summary="Planning sur 4 semaines (nominatif pour le prêtre, initiales pour le secrétariat)",
        parameters=[PlanningFilterSerializer],
        responses=PlanningSlotSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        filters = PlanningFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        slots = selectors.planning_for(
            user=request.user,
            node_id=filters.validated_data.get("node"),
            date_from=filters.validated_data.get("date_from"),
        )
        return Response(PlanningSlotSerializer(slots, many=True, context={"request": request}).data)


class SlotCancelApi(_PriestApi):
    @extend_schema(
        tags=TAG,
        summary="Annuler un de mes créneaux (le réservant est prévenu)",
        request=SlotCancelInputSerializer,
        responses=SlotOutputSerializer,
    )
    def post(self, request: Request, slot_id: int) -> Response:
        slot = selectors.slot_get_for_priest(user=request.user, slot_id=slot_id)
        serializer = SlotCancelInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        slot = services.slot_cancel_by_priest(slot=slot, actor=request.user, **serializer.validated_data)
        return Response(SlotOutputSerializer(selectors.slot_get_for_priest(user=request.user, slot_id=slot.pk)).data)


class AttendanceApi(_PriestApi):
    @extend_schema(
        tags=TAG,
        summary="Marquer le rendez-vous honoré ou absent",
        request=AttendanceInputSerializer,
        responses={204: None},
    )
    def post(self, request: Request, booking_id: int) -> Response:
        booking = selectors.booking_get_for_priest(user=request.user, booking_id=booking_id)
        serializer = AttendanceInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.booking_attendance_set(booking=booking, actor=request.user, **serializer.validated_data)
        return Response(status=status.HTTP_204_NO_CONTENT)
