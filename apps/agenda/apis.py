import csv
import io

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agenda import selectors, services
from apps.agenda.serializers import (
    EventCreateInputSerializer,
    EventFilterSerializer,
    EventOutputSerializer,
    EventUpdateInputSerializer,
    RegistrationOutputSerializer,
    StaffEventFilterSerializer,
    registrations_csv_rows,
)
from apps.api.mixins import ApiAuthMixin, PermissionClassesType
from apps.api.pagination import LimitOffsetPagination, get_paginated_response, paginated_response_serializer
from apps.api.v1 import V1ApiMixin
from apps.hierarchy import authz
from apps.hierarchy import selectors as hierarchy_selectors
from apps.hierarchy.authz import HasCapability

TAG = ["agenda"]
_PAGINATION = [
    OpenApiParameter("limit", int, description="Nombre de résultats (défaut 10, max 50)"),
    OpenApiParameter("offset", int, description="Décalage"),
]


class _PublicApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes: PermissionClassesType = (AllowAny,)


class _AuthedApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes: PermissionClassesType = (IsAuthenticated,)


class _StaffApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes: PermissionClassesType = (IsAuthenticated, HasCapability("evenements.gerer"))

    def get_permissions(self):
        if authz.peut(self.request.user, "plateforme.admin", None):
            return [IsAuthenticated()]
        return super().get_permissions()


# --- Public / fidèle ----------------------------------------------------------------------


class EventListApi(_PublicApi):
    @extend_schema(
        tags=TAG,
        operation_id="agenda_list",
        summary="Événements à venir (filtres : nœud et sous-arbre, période, type)",
        parameters=[EventFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(EventOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = EventFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        data = filters.validated_data
        node = hierarchy_selectors.node_get(node_id=data["node"]) if data.get("node") else None
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=EventOutputSerializer,
            queryset=selectors.event_list_public(
                node=node,
                date_from=data.get("date_from"),
                date_to=data.get("date_to"),
                event_type=data.get("type"),
                viewer=request.user,
            ),
            request=request,
            view=self,
        )


class EventDetailApi(_PublicApi):
    @extend_schema(tags=TAG, summary="Détail d'un événement", responses=EventOutputSerializer)
    def get(self, request: Request, event_id: int) -> Response:
        return Response(EventOutputSerializer(selectors.event_get_public(event_id=event_id, viewer=request.user)).data)


class EventRegisterApi(_AuthedApi):
    @extend_schema(
        tags=TAG,
        summary="S'inscrire (409 si complet ; idempotent)",
        request=None,
        responses={201: EventOutputSerializer, 409: OpenApiResponse(description="Événement complet")},
    )
    def post(self, request: Request, event_id: int) -> Response:
        event = selectors.event_get_public(event_id=event_id)
        services.event_register(event=event, user=request.user)
        return Response(
            EventOutputSerializer(selectors.event_get_public(event_id=event_id, viewer=request.user)).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(tags=TAG, summary="Se désinscrire", responses={204: None})
    def delete(self, request: Request, event_id: int) -> Response:
        services.event_unregister(event=selectors.event_get_public(event_id=event_id), user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Staff --------------------------------------------------------------------------------


class StaffEventListCreateApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        operation_id="staff_agenda_list",
        summary="Événements à gérer (evenements.gerer)",
        parameters=[StaffEventFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(EventOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = StaffEventFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=EventOutputSerializer,
            queryset=selectors.event_list_for_staff(user=request.user, filters=filters.validated_data),
            request=request,
            view=self,
        )

    @extend_schema(
        tags=TAG, summary="Créer un événement", request=EventCreateInputSerializer, responses={201: EventOutputSerializer}
    )
    def post(self, request: Request) -> Response:
        serializer = EventCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        node_id, place_id = data.pop("node_id", None), data.pop("place_id", None)
        node = hierarchy_selectors.node_get(node_id=node_id) if node_id else None
        place = hierarchy_selectors.place_get(place_id=place_id) if place_id else None
        event = services.event_create(organizer=request.user, node=node, place=place, **data)
        return Response(
            EventOutputSerializer(selectors.event_get_for_staff(user=request.user, event_id=event.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class StaffEventDetailApi(_StaffApi):
    @extend_schema(tags=TAG, summary="Détail (staff)", responses=EventOutputSerializer)
    def get(self, request: Request, event_id: int) -> Response:
        return Response(EventOutputSerializer(selectors.event_get_for_staff(user=request.user, event_id=event_id)).data)

    @extend_schema(tags=TAG, summary="Modifier un événement", request=EventUpdateInputSerializer, responses=EventOutputSerializer)
    def patch(self, request: Request, event_id: int) -> Response:
        event = selectors.event_get_for_staff(user=request.user, event_id=event_id)
        serializer = EventUpdateInputSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.event_update(event=event, actor=request.user, data=dict(serializer.validated_data))
        return Response(EventOutputSerializer(selectors.event_get_for_staff(user=request.user, event_id=event_id)).data)

    @extend_schema(tags=TAG, summary="Annuler un événement (les inscrits sont prévenus)", responses={204: None})
    def delete(self, request: Request, event_id: int) -> Response:
        services.event_cancel(event=selectors.event_get_for_staff(user=request.user, event_id=event_id), actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StaffEventRegistrationsApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        summary="Liste des inscrits",
        parameters=_PAGINATION,
        responses=paginated_response_serializer(RegistrationOutputSerializer),
    )
    def get(self, request: Request, event_id: int) -> Response:
        event = selectors.event_get_for_staff(user=request.user, event_id=event_id)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=RegistrationOutputSerializer,
            queryset=selectors.event_registrations(event=event),
            request=request,
            view=self,
        )


class StaffEventRegistrationsCsvApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        summary="Export CSV des inscrits",
        responses={(200, "text/csv"): OpenApiTypes.STR},
    )
    def get(self, request: Request, event_id: int) -> HttpResponse:
        event = selectors.event_get_for_staff(user=request.user, event_id=event_id)
        buffer = io.StringIO()
        buffer.write("﻿")  # BOM : Excel lit l'UTF-8 correctement
        csv.writer(buffer, delimiter=";").writerows(registrations_csv_rows(selectors.event_registrations(event=event)))
        response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="inscrits-evenement-{event.pk}.csv"'
        return response
