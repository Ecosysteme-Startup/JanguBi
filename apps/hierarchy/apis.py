from dataclasses import asdict
from datetime import timedelta
from typing import Any

from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import SAFE_METHODS, AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin
from apps.api.pagination import LimitOffsetPagination, paginated_response_serializer
from apps.api.v1 import V1ApiMixin
from apps.core.exceptions import ApplicationError
from apps.hierarchy import selectors, services
from apps.hierarchy.enums import NodeStatus
from apps.hierarchy.imports import nodes_import_csv, places_import_csv
from apps.hierarchy.models import Node
from apps.hierarchy.serializers import (
    DirectoryFilterSerializer,
    ImportInputSerializer,
    ImportQuerySerializer,
    ImportReportSerializer,
    NodeCreateInputSerializer,
    NodeFilterSerializer,
    NodeOutputSerializer,
    NodeTypeOutputSerializer,
    NodeUpdateInputSerializer,
    NodeWeekOutputSerializer,
    PlaceCreateInputSerializer,
    PlaceOutputSerializer,
    PlaceUpdateInputSerializer,
    ScheduleExceptionSerializer,
    ScheduleReplaceInputSerializer,
    ScheduleSerializer,
    WeekQuerySerializer,
)
from apps.users.permissions import IsSuperAdmin

TAG = ["hierarchy"]
PUBLIC_TAG = ["public"]


class HierarchyBaseApi(V1ApiMixin, ApiAuthMixin, APIView):
    """Lecture publique ; écriture réservée au super-admin.

    TODO(L2) : remplacer IsSuperAdmin par HasCapability("structure.gerer" | "horaires.gerer").
    """

    def get_permissions(self):
        if self.request.method in SAFE_METHODS:
            return [AllowAny()]
        return [IsAuthenticated(), IsSuperAdmin()]


def _node_list_response(*, request: Request, view: APIView, queryset) -> Response:
    paginator = LimitOffsetPagination()
    page = paginator.paginate_queryset(queryset, request, view=view) or []
    context = {"parent_ids": selectors.node_parent_ids(nodes=page)}
    return paginator.get_paginated_response(NodeOutputSerializer(page, many=True, context=context).data)


def _node_data(node: Node) -> dict[str, Any]:
    context = {"parent_ids": selectors.node_parent_ids(nodes=[node])}
    return NodeOutputSerializer(node, context=context).data


def _resolve_node_refs(data: dict[str, Any]) -> dict[str, Any]:
    """Transforme ``located_in_id`` en instance de nœud."""
    data = dict(data)
    if "located_in_id" in data:
        located = data.pop("located_in_id")
        data["located_in"] = selectors.node_get(node_id=located) if located else None
    return data


# --- Types et nœuds ------------------------------------------------------------


class NodeTypeListApi(HierarchyBaseApi):
    @extend_schema(tags=TAG, summary="Types de nœuds et parents autorisés", responses=NodeTypeOutputSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(NodeTypeOutputSerializer(selectors.node_type_list(), many=True).data)


class NodeListCreateApi(HierarchyBaseApi):
    @extend_schema(
        tags=TAG,
        summary="Lister les nœuds (filtres type, parent, within, q, city, status, on_platform)",
        parameters=[
            NodeFilterSerializer,
            OpenApiParameter("limit", int, description="Nombre de résultats (défaut 10, max 50)"),
            OpenApiParameter("offset", int, description="Décalage"),
        ],
        responses=paginated_response_serializer(NodeOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = NodeFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        data = dict(filters.validated_data)
        # Les nœuds supprimés ne sont listés qu'aux administrateurs du référentiel.
        if data.get("status") == NodeStatus.SUPPRIME and not IsSuperAdmin().has_permission(request, self):
            raise PermissionDenied("Seuls les administrateurs voient les nœuds supprimés.")
        return _node_list_response(request=request, view=self, queryset=selectors.node_list(filters=data))

    @extend_schema(
        tags=TAG,
        summary="Créer un nœud (structure.gerer)",
        request=NodeCreateInputSerializer,
        responses={201: NodeOutputSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = NodeCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = _resolve_node_refs(serializer.validated_data)
        node_type = selectors.node_type_get_by_code(code=data.pop("type"))
        parent_id = data.pop("parent_id", None)
        parent = selectors.node_get(node_id=parent_id) if parent_id else None
        node = services.node_create(node_type=node_type, parent=parent, **data)
        return Response(_node_data(selectors.node_get(node_id=node.pk)), status=status.HTTP_201_CREATED)


class NodeDetailApi(HierarchyBaseApi):
    @extend_schema(tags=TAG, summary="Détail d'un nœud", responses=NodeOutputSerializer)
    def get(self, request: Request, node_id: str) -> Response:
        return Response(_node_data(selectors.node_get(node_id=node_id)))

    @extend_schema(
        tags=TAG,
        summary="Modifier un nœud ou son statut (structure.gerer)",
        request=NodeUpdateInputSerializer,
        responses=NodeOutputSerializer,
    )
    def patch(self, request: Request, node_id: str) -> Response:
        node = selectors.node_get(node_id=node_id)
        serializer = NodeUpdateInputSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.node_update(node=node, data=_resolve_node_refs(serializer.validated_data))
        return Response(_node_data(selectors.node_get(node_id=node.pk)))


class NodeChildrenApi(HierarchyBaseApi):
    @extend_schema(tags=TAG, summary="Enfants directs d'un nœud", responses=NodeOutputSerializer(many=True))
    def get(self, request: Request, node_id: str) -> Response:
        node = selectors.node_get(node_id=node_id)
        children = list(selectors.node_children(node=node))
        parent_ids = {node.path: str(node.pk)}
        return Response(NodeOutputSerializer(children, many=True, context={"parent_ids": parent_ids}).data)


class NodeAncestorsApi(HierarchyBaseApi):
    @extend_schema(tags=TAG, summary="Ancêtres d'un nœud (de la racine au parent)", responses=NodeOutputSerializer(many=True))
    def get(self, request: Request, node_id: str) -> Response:
        node = selectors.node_get(node_id=node_id)
        ancestors = list(selectors.node_ancestors(node=node))
        parent_ids = {a.path: str(a.pk) for a in ancestors}
        return Response(NodeOutputSerializer(ancestors, many=True, context={"parent_ids": parent_ids}).data)


# --- Lieux de culte -------------------------------------------------------------


class NodePlaceListCreateApi(HierarchyBaseApi):
    @extend_schema(tags=TAG, summary="Lieux de culte d'un nœud", responses=PlaceOutputSerializer(many=True))
    def get(self, request: Request, node_id: str) -> Response:
        node = selectors.node_get(node_id=node_id)
        return Response(PlaceOutputSerializer(selectors.place_list(node=node), many=True).data)

    @extend_schema(
        tags=TAG,
        summary="Ajouter un lieu de culte (structure.gerer)",
        request=PlaceCreateInputSerializer,
        responses={201: PlaceOutputSerializer},
    )
    def post(self, request: Request, node_id: str) -> Response:
        node = selectors.node_get(node_id=node_id)
        serializer = PlaceCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        place = services.place_create(node=node, **serializer.validated_data)
        return Response(PlaceOutputSerializer(place).data, status=status.HTTP_201_CREATED)


class PlaceDetailApi(HierarchyBaseApi):
    @extend_schema(tags=TAG, summary="Détail d'un lieu de culte", responses=PlaceOutputSerializer)
    def get(self, request: Request, place_id: int) -> Response:
        return Response(PlaceOutputSerializer(selectors.place_get(place_id=place_id)).data)

    @extend_schema(
        tags=TAG,
        summary="Modifier un lieu de culte (structure.gerer)",
        request=PlaceUpdateInputSerializer,
        responses=PlaceOutputSerializer,
    )
    def patch(self, request: Request, place_id: int) -> Response:
        place = selectors.place_get(place_id=place_id)
        serializer = PlaceUpdateInputSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        place = services.place_update(place=place, data=dict(serializer.validated_data))
        return Response(PlaceOutputSerializer(place).data)


class PlaceScheduleApi(HierarchyBaseApi):
    @extend_schema(tags=TAG, summary="Semaine type d'un lieu de culte", responses=ScheduleSerializer(many=True))
    def get(self, request: Request, place_id: int) -> Response:
        place = selectors.place_get(place_id=place_id)
        return Response(ScheduleSerializer(selectors.schedule_list(place=place), many=True).data)

    @extend_schema(
        tags=TAG,
        summary="Remplacer la semaine type d'un lieu de culte (horaires.gerer)",
        request=ScheduleReplaceInputSerializer,
        responses=ScheduleSerializer(many=True),
    )
    def put(self, request: Request, place_id: int) -> Response:
        place = selectors.place_get(place_id=place_id)
        serializer = ScheduleReplaceInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedules = services.schedule_replace(place=place, items=serializer.validated_data["items"])
        return Response(ScheduleSerializer(schedules, many=True).data)


class PlaceExceptionListCreateApi(HierarchyBaseApi):
    @extend_schema(
        tags=TAG,
        summary="Exceptions d'horaire à venir d'un lieu de culte",
        responses=ScheduleExceptionSerializer(many=True),
    )
    def get(self, request: Request, place_id: int) -> Response:
        place = selectors.place_get(place_id=place_id)
        exceptions = selectors.schedule_exception_list(place=place, date_from=timezone.localdate())
        return Response(ScheduleExceptionSerializer(exceptions, many=True).data)

    @extend_schema(
        tags=TAG,
        summary="Ajouter une exception (annulation ou horaire supplémentaire) (horaires.gerer)",
        request=ScheduleExceptionSerializer,
        responses={201: ScheduleExceptionSerializer},
    )
    def post(self, request: Request, place_id: int) -> Response:
        place = selectors.place_get(place_id=place_id)
        serializer = ScheduleExceptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        exception = services.schedule_exception_create(place=place, **serializer.validated_data)
        return Response(ScheduleExceptionSerializer(exception).data, status=status.HTTP_201_CREATED)


class PlaceExceptionDeleteApi(HierarchyBaseApi):
    @extend_schema(tags=TAG, summary="Supprimer une exception d'horaire (horaires.gerer)", responses={204: None})
    def delete(self, request: Request, place_id: int, exception_id: int) -> Response:
        place = selectors.place_get(place_id=place_id)
        services.schedule_exception_delete(
            exception=selectors.schedule_exception_get(place=place, exception_id=exception_id)
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Import CSV -----------------------------------------------------------------


class _ImportApi(HierarchyBaseApi):
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    importer = staticmethod(nodes_import_csv)

    def post(self, request: Request) -> Response:
        serializer = ImportInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        query = ImportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        dry_run = query.validated_data["dry_run"]
        try:
            content = serializer.validated_data["file"].read().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ApplicationError("Le fichier doit être encodé en UTF-8.", code="csv_encoding") from exc
        report = self.importer(content=content, dry_run=dry_run)
        return Response(ImportReportSerializer(report.as_dict()).data)


_IMPORT_PARAMS = [ImportQuerySerializer]


class NodeImportApi(_ImportApi):
    importer = staticmethod(nodes_import_csv)

    @extend_schema(
        tags=TAG,
        summary="Importer des nœuds (CSV : code, type, name, parent_code…) (structure.gerer)",
        parameters=_IMPORT_PARAMS,
        request={"multipart/form-data": ImportInputSerializer},
        responses=ImportReportSerializer,
    )
    def post(self, request: Request) -> Response:
        return super().post(request)


class PlaceImportApi(_ImportApi):
    importer = staticmethod(places_import_csv)

    @extend_schema(
        tags=TAG,
        summary="Importer des lieux de culte (CSV : node_code, name, kind…) (structure.gerer)",
        parameters=_IMPORT_PARAMS,
        request={"multipart/form-data": ImportInputSerializer},
        responses=ImportReportSerializer,
    )
    def post(self, request: Request) -> Response:
        return super().post(request)


# --- Public ---------------------------------------------------------------------


class PublicDirectoryApi(HierarchyBaseApi):
    @extend_schema(
        tags=PUBLIC_TAG,
        summary="Annuaire public des paroisses (recherche par nom, ville, diocèse)",
        parameters=[
            DirectoryFilterSerializer,
            OpenApiParameter("limit", int, description="Nombre de résultats (défaut 10, max 50)"),
            OpenApiParameter("offset", int, description="Décalage"),
        ],
        responses=paginated_response_serializer(NodeOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = DirectoryFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        data = dict(filters.validated_data)
        if diocese := data.pop("diocese", None):
            data["within"] = diocese
        return _node_list_response(request=request, view=self, queryset=selectors.node_list(filters=data))


class PublicNodeWeekApi(HierarchyBaseApi):
    @extend_schema(
        tags=PUBLIC_TAG,
        summary="Semaine des horaires d'un nœud (messes, confessions, adoration ; exceptions comprises)",
        parameters=[WeekQuerySerializer],
        responses=NodeWeekOutputSerializer,
    )
    def get(self, request: Request, node_id: str) -> Response:
        query = WeekQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        start = query.validated_data.get("start") or timezone.localdate()
        node = selectors.node_get(node_id=node_id)
        places, occurrences = selectors.node_week(node=node, start=start)
        names = {p.pk: p.name for p in places}
        payload = {
            "node": node,
            "start": start,
            "end": start + timedelta(days=6),
            "places": places,
            "occurrences": [{**asdict(o), "place_name": names[o.place_id]} for o in occurrences],
        }
        return Response(NodeWeekOutputSerializer(payload).data)
