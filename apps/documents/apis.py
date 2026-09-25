from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin, PermissionClassesType
from apps.api.pagination import LimitOffsetPagination, get_paginated_response, paginated_response_serializer
from apps.api.v1 import V1ApiMixin
from apps.core.exceptions import NotFoundError
from apps.documents import selectors, services
from apps.documents.constants import allowed_reasons_for
from apps.documents.models import DocumentRequest
from apps.documents.serializers import (
    CountsOutputSerializer,
    NodeQuerySerializer,
    NoteInputSerializer,
    NoteOutputSerializer,
    ProcessorOutputSerializer,
    QueueFilterSerializer,
    QueueItemSerializer,
    RegisterRefInputSerializer,
    RequestCreateInputSerializer,
    RequesterFilterSerializer,
    RequesterOutputSerializer,
    StatsOutputSerializer,
    StatusLogSerializer,
    SupplementInputSerializer,
    TransitionInputSerializer,
)
from apps.hierarchy import selectors as hierarchy_selectors
from apps.hierarchy.authz import HasCapability

TAG = ["documents"]
_PAGINATION = [
    OpenApiParameter("limit", int, description="Nombre de résultats (défaut 10, max 50)"),
    OpenApiParameter("offset", int, description="Décalage"),
]


class _AuthedApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes: PermissionClassesType = (IsAuthenticated,)


class _ProcessorApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes: PermissionClassesType = (IsAuthenticated, HasCapability("actes.traiter"))


# --- Fidèle --------------------------------------------------------------------------------


class RequestListCreateApi(_AuthedApi):
    @extend_schema(
        tags=TAG,
        operation_id="documents_requests_list",
        summary="Mes demandes d'actes",
        parameters=[RequesterFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(RequesterOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = RequesterFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=RequesterOutputSerializer,
            queryset=selectors.request_list_for_requester(user=request.user, status=filters.validated_data.get("status")),
            request=request,
            view=self,
        )

    @extend_schema(
        tags=TAG,
        summary="Demander un acte à la paroisse du sacrement",
        request=RequestCreateInputSerializer,
        responses={201: RequesterOutputSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = RequestCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        target = hierarchy_selectors.node_get(node_id=data.pop("target_node_id"))
        request_obj = services.document_request_create(requester=request.user, target_node=target, data=data)
        return Response(
            RequesterOutputSerializer(selectors.request_get_for_requester(user=request.user, request_id=request_obj.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class RequestOptionsApi(_AuthedApi):
    @extend_schema(
        tags=TAG,
        summary="Options du formulaire (types, motifs, compatibilités, modes de retrait)",
        responses=inline_serializer(
            "DocumentRequestOptions",
            {
                "document_types": serializers.ListField(child=serializers.DictField()),
                "reasons": serializers.ListField(child=serializers.DictField()),
                "pickup_modes": serializers.ListField(child=serializers.DictField()),
            },
        ),
    )
    def get(self, request: Request) -> Response:
        return Response(
            {
                "document_types": [
                    {
                        "value": value,
                        "label": str(label),
                        "requires_precision": value == DocumentRequest.DocumentType.OTHER,
                        "allowed_reasons": list(allowed_reasons_for(value)),
                    }
                    for value, label in DocumentRequest.DocumentType.choices
                ],
                "reasons": [{"value": v, "label": str(label)} for v, label in DocumentRequest.RequestReason.choices],
                "pickup_modes": [{"value": v, "label": str(label)} for v, label in DocumentRequest.PickupMode.choices],
            }
        )


class RequestDetailApi(_AuthedApi):
    @extend_schema(tags=TAG, summary="Suivi de ma demande (statut, historique, retrait)", responses=RequesterOutputSerializer)
    def get(self, request: Request, request_id: str) -> Response:
        obj = selectors.request_get_for_requester(user=request.user, request_id=request_id)
        return Response(RequesterOutputSerializer(obj, context={"with_history": True}).data)


class RequestSupplementApi(_AuthedApi):
    @extend_schema(tags=TAG, summary="Envoyer le complément demandé", request=SupplementInputSerializer, responses=RequesterOutputSerializer)
    def post(self, request: Request, request_id: str) -> Response:
        obj = selectors.request_get_for_requester(user=request.user, request_id=request_id)
        serializer = SupplementInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.document_request_submit_supplement(request_obj=obj, requester=request.user, **serializer.validated_data)
        obj = selectors.request_get_for_requester(user=request.user, request_id=request_id)
        return Response(RequesterOutputSerializer(obj, context={"with_history": True}).data)


class RequestCancelApi(_AuthedApi):
    @extend_schema(tags=TAG, summary="Annuler ma demande (soumise ou en complément)", request=None, responses=RequesterOutputSerializer)
    def post(self, request: Request, request_id: str) -> Response:
        obj = selectors.request_get_for_requester(user=request.user, request_id=request_id)
        services.document_request_cancel(request_obj=obj, requester=request.user)
        return Response(RequesterOutputSerializer(selectors.request_get_for_requester(user=request.user, request_id=request_id)).data)


# --- Paroisse -----------------------------------------------------------------------------


class QueueApi(_ProcessorApi):
    @extend_schema(
        tags=TAG,
        operation_id="staff_documents_list",
        summary="File de traitement (actes.traiter)",
        parameters=[QueueFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(QueueItemSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = QueueFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=QueueItemSerializer,
            queryset=selectors.queue_for(user=request.user, filters=filters.validated_data),
            request=request,
            view=self,
        )


class QueueCountsApi(_ProcessorApi):
    @extend_schema(tags=TAG, summary="Compteurs par statut de ma file", parameters=[NodeQuerySerializer], responses=CountsOutputSerializer)
    def get(self, request: Request) -> Response:
        query = NodeQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(selectors.status_counts(queryset=selectors.queue_for(user=request.user, filters=query.validated_data)))


class SupervisionStatsApi(_AuthedApi):
    permission_classes = (IsAuthenticated, HasCapability("actes.superviser"))

    @extend_schema(
        tags=TAG,
        summary="Indicateurs agrégés, sans nom (actes.superviser)",
        parameters=[NodeQuerySerializer],
        responses=StatsOutputSerializer,
    )
    def get(self, request: Request) -> Response:
        query = NodeQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(selectors.supervision_stats(user=request.user, node_id=query.validated_data.get("node")))


class ProcessorDetailApi(_ProcessorApi):
    @extend_schema(tags=TAG, summary="Détail d'une demande de ma file", responses=ProcessorOutputSerializer)
    def get(self, request: Request, request_id: str) -> Response:
        obj = selectors.request_get_for_processor(user=request.user, request_id=request_id)
        return Response(ProcessorOutputSerializer(obj, context={"with_history": True}).data)


_ACTIONS = {
    "start-verification": "start_verification",
    "request-info": "request_info",
    "mark-ready": "mark_ready",
    "mark-collected": "mark_collected",
    "reject": "reject",
}


class ProcessorTransitionApi(_ProcessorApi):
    @extend_schema(
        tags=TAG,
        summary="Faire avancer la demande (start-verification, request-info, mark-ready, mark-collected, reject)",
        request=TransitionInputSerializer,
        responses=ProcessorOutputSerializer,
    )
    def post(self, request: Request, request_id: str, transition: str) -> Response:
        if transition not in _ACTIONS:
            raise NotFoundError("Action inconnue.", {"transition": transition})
        obj = selectors.request_get_for_processor(user=request.user, request_id=request_id)
        serializer = TransitionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        place_id = data.get("pickup_place_id")
        services.document_request_process(
            request_obj=obj,
            actor=request.user,
            action=_ACTIONS[transition],
            message=data["message"],
            pickup_place=hierarchy_selectors.place_get(place_id=place_id) if place_id else None,
            pickup_hours=data["pickup_hours"],
        )
        obj = selectors.request_get_for_processor(user=request.user, request_id=request_id)
        return Response(ProcessorOutputSerializer(obj, context={"with_history": True}).data)


class RegisterRefApi(_ProcessorApi):
    @extend_schema(tags=TAG, summary="Références du registre (jamais visibles du fidèle)", request=RegisterRefInputSerializer, responses=ProcessorOutputSerializer)
    def put(self, request: Request, request_id: str) -> Response:
        obj = selectors.request_get_for_processor(user=request.user, request_id=request_id)
        serializer = RegisterRefInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.document_request_register_ref_set(request_obj=obj, actor=request.user, data=serializer.validated_data)
        return Response(ProcessorOutputSerializer(selectors.request_get_for_processor(user=request.user, request_id=request_id)).data)


class NotesApi(_ProcessorApi):
    @extend_schema(tags=TAG, summary="Notes internes (jamais visibles du fidèle)", responses=NoteOutputSerializer(many=True))
    def get(self, request: Request, request_id: str) -> Response:
        obj = selectors.request_get_for_processor(user=request.user, request_id=request_id)
        return Response(NoteOutputSerializer(selectors.internal_notes(request_obj=obj), many=True).data)

    @extend_schema(tags=TAG, summary="Ajouter une note interne", request=NoteInputSerializer, responses={201: NoteOutputSerializer})
    def post(self, request: Request, request_id: str) -> Response:
        obj = selectors.request_get_for_processor(user=request.user, request_id=request_id)
        serializer = NoteInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = services.document_request_add_internal_note(request_obj=obj, author=request.user, **serializer.validated_data)
        return Response(NoteOutputSerializer(note).data, status=status.HTTP_201_CREATED)


class LogsApi(_ProcessorApi):
    @extend_schema(tags=TAG, summary="Journal des statuts", responses=StatusLogSerializer(many=True))
    def get(self, request: Request, request_id: str) -> Response:
        obj = selectors.request_get_for_processor(user=request.user, request_id=request_id)
        return Response(StatusLogSerializer(selectors.status_logs(request_obj=obj), many=True).data)

