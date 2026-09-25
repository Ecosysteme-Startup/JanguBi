from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin
from apps.api.v1 import V1ApiMixin
from apps.dashboards import selectors
from apps.hierarchy import selectors as hierarchy_selectors
from apps.hierarchy.authz import HasCapability, node_from_kwarg

TAG = ["dashboards"]


class PeriodSerializer(serializers.Serializer):
    period = serializers.ChoiceField(choices=selectors.PERIODS, default=30, help_text="Fenêtre en jours")


class NodeDashboardApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated, HasCapability("tableau_bord.voir", node_resolver=node_from_kwarg()))

    @extend_schema(
        tags=TAG,
        summary="Tableau de bord d'un nœud, agrégé sur son sous-arbre (aucune donnée nominative)",
        parameters=[PeriodSerializer],
        responses=OpenApiTypes.OBJECT,
    )
    def get(self, request: Request, node_id: str) -> Response:
        query = PeriodSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        node = hierarchy_selectors.node_get(node_id=node_id)
        return Response(selectors.node_dashboard(node=node, period=query.validated_data["period"]))


class PlatformDashboardApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated, HasCapability("plateforme.admin"))

    @extend_schema(
        tags=TAG,
        summary="Tableau de bord plateforme : comptes, MFA du staff, santé des files et de Beat",
        responses=OpenApiTypes.OBJECT,
    )
    def get(self, request: Request) -> Response:
        return Response(selectors.platform_dashboard())
