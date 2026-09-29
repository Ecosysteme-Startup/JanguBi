"""Équipe des compteurs de quête (lot V1-routes, G08) : couche HTTP."""

from typing import Any

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin, PermissionClassesType
from apps.api.v1 import V1ApiMixin
from apps.core.exceptions import ApplicationError
from apps.donations import access, selectors_compteurs, services_compteurs
from apps.hierarchy import selectors as hierarchy_selectors
from apps.hierarchy.authz import HasCapability

TAG = ["dons"]


class CounterSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nom = serializers.CharField(source="name")
    actif = serializers.BooleanField(source="is_active")
    ajoute_le = serializers.DateTimeField(source="created_at")


class CounterTeamSerializer(serializers.Serializer):
    compteurs = CounterSerializer(many=True)
    noms_recents = serializers.ListField(
        child=serializers.CharField(), help_text="Noms vus dans les quêtes des 90 derniers jours, hors équipe"
    )


class CounterQuerySerializer(serializers.Serializer):
    node = serializers.UUIDField(help_text="Paroisse")


class CounterCreateInputSerializer(serializers.Serializer):
    node = serializers.UUIDField()
    nom = serializers.CharField(max_length=120)


class CounterUpdateInputSerializer(serializers.Serializer):
    nom = serializers.CharField(max_length=120)


def _parish(node_id: Any) -> Any:
    node = hierarchy_selectors.node_get(node_id=node_id)
    if not access.is_parish(node):
        raise ApplicationError("Ce nœud n'est pas une paroisse.", code="not_a_parish")
    return node


class _CounterApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes: PermissionClassesType = (IsAuthenticated, HasCapability("dons.saisir_quete"))


class CounterListCreateApi(_CounterApi):
    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_compteurs_list",
        summary="Équipe des compteurs de quête d'une paroisse (et noms récents hors équipe)",
        parameters=[CounterQuerySerializer],
        responses=CounterTeamSerializer,
    )
    def get(self, request: Request) -> Response:
        query = CounterQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        node = _parish(query.validated_data["node"])
        access.require_parish_level(request.user, "dons.saisir_quete", node)
        data = {
            "compteurs": selectors_compteurs.counters_for_parish(node=node),
            "noms_recents": selectors_compteurs.counter_recent_names(node=node),
        }
        return Response(CounterTeamSerializer(data).data)

    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_compteurs_create",
        summary="Ajouter un compteur à l'équipe",
        request=CounterCreateInputSerializer,
        responses={201: CounterSerializer},
    )
    def post(self, request: Request) -> Response:
        body = CounterCreateInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        counter = services_compteurs.counter_add(
            actor=request.user, node=_parish(body.validated_data["node"]), name=body.validated_data["nom"]
        )
        return Response(CounterSerializer(counter).data, status=status.HTTP_201_CREATED)


class CounterDetailApi(_CounterApi):
    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_compteurs_update",
        summary="Corriger le nom d'un compteur",
        parameters=[OpenApiParameter("counter_id", int, OpenApiParameter.PATH)],
        request=CounterUpdateInputSerializer,
        responses=CounterSerializer,
    )
    def patch(self, request: Request, counter_id: int) -> Response:
        body = CounterUpdateInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        counter = selectors_compteurs.counter_get(counter_id=counter_id)
        counter = services_compteurs.counter_rename(actor=request.user, counter=counter, name=body.validated_data["nom"])
        return Response(CounterSerializer(counter).data)

    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_compteurs_remove",
        summary="Retirer un compteur de l'équipe (désactivé, jamais effacé)",
        parameters=[OpenApiParameter("counter_id", int, OpenApiParameter.PATH)],
        responses={204: None},
    )
    def delete(self, request: Request, counter_id: int) -> Response:
        counter = selectors_compteurs.counter_get(counter_id=counter_id)
        services_compteurs.counter_remove(actor=request.user, counter=counter)
        return Response(status=status.HTTP_204_NO_CONTENT)
