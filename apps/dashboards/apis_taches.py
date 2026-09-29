"""Tâches du jour d'une paroisse (lot V1-routes, G01) : couche HTTP."""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin
from apps.api.v1 import V1ApiMixin
from apps.core.exceptions import PermissionDeniedError
from apps.dashboards import selectors_taches
from apps.hierarchy import selectors as hierarchy_selectors
from apps.hierarchy.authz import HasAnyCapability, peut

TAG = ["staff"]


class TasksQuerySerializer(serializers.Serializer):
    node = serializers.UUIDField(help_text="Paroisse")
    date = serializers.DateField(required=False, help_text="Par défaut : aujourd'hui")


class _NodeRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class TaskSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    count = serializers.IntegerField()


class ConfessionOfDaySerializer(serializers.Serializer):
    slot_id = serializers.IntegerField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    place_name = serializers.CharField()
    priest_name = serializers.CharField()
    reserved = serializers.BooleanField()


class TodayTasksSerializer(serializers.Serializer):
    node = _NodeRefSerializer()
    date = serializers.DateField()
    tasks = TaskSerializer(many=True)
    confessions = ConfessionOfDaySerializer(
        many=True, allow_null=True, help_text="null sans capacité confessions (gérer ou voir le planning)"
    )


class TodayTasksApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated, HasAnyCapability(*selectors_taches.TASK_CAPABILITIES))

    @extend_schema(
        tags=TAG,
        operation_id="staff_taches_du_jour",
        summary="Tâches du jour de la paroisse (demandes, quêtes, annonces, intentions, confessions)",
        parameters=[TasksQuerySerializer],
        responses=TodayTasksSerializer,
    )
    def get(self, request: Request) -> Response:
        query = TasksQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        node = hierarchy_selectors.node_get(node_id=query.validated_data["node"])
        if not any(peut(request.user, c, node) for c in selectors_taches.TASK_CAPABILITIES):
            raise PermissionDeniedError("Vous n'avez pas de tâche sur ce nœud.", code="taches_forbidden")
        data = selectors_taches.today_tasks(user=request.user, node=node, day=query.validated_data.get("date"))
        return Response(TodayTasksSerializer(data).data)
