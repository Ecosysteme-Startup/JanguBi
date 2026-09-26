from typing import Any

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin, PermissionClassesType
from apps.api.pagination import LimitOffsetPagination, get_paginated_response, paginated_response_serializer
from apps.api.v1 import V1ApiMixin
from apps.core.exceptions import ApplicationError, NotFoundError
from apps.core.request_context import client_ip
from apps.hierarchy import authz, selectors, selectors_offices, services_offices
from apps.hierarchy.authz import HasCapability
from apps.hierarchy.imports import assignments_import_csv
from apps.hierarchy.models import Capability, CapabilityOverride
from apps.hierarchy.serializers import (
    AssignmentCreateInputSerializer,
    AssignmentFilterSerializer,
    AssignmentImportQuerySerializer,
    AssignmentOutputSerializer,
    AssignmentUpdateInputSerializer,
    AuditEventOutputSerializer,
    AuditFilterSerializer,
    CapabilityOverrideSerializer,
    CapaciteOutputSerializer,
    DeclarationInputSerializer,
    ImportInputSerializer,
    ImportReportSerializer,
    NodeRefSerializer,
    OfficeTypeOutputSerializer,
    PersonSearchFilterSerializer,
    PersonSearchOutputSerializer,
    PersonStatusOutputSerializer,
    VerificationDecisionInputSerializer,
    VerificationFilterSerializer,
)

TAG = ["hierarchy"]
ME_TAG = ["me"]
AUDIT_TAG = ["audit"]

_PAGINATION = [
    OpenApiParameter("limit", int, description="Nombre de résultats (défaut 10, max 50)"),
    OpenApiParameter("offset", int, description="Décalage"),
]


def _ip(request: Request) -> str | None:
    return client_ip(request.META)


class _StaffMfa(BasePermission):
    """Un responsable (titulaire d'office) connecté par Keycloak doit l'être avec MFA."""

    def has_permission(self, request: Request, view: Any) -> bool:
        authz.mfa_check(request.user)
        return True


class AuthedV1Api(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes: PermissionClassesType = (IsAuthenticated, _StaffMfa)


# --- Offices et nominations -------------------------------------------------------------


class OfficeTypeListApi(AuthedV1Api):
    @extend_schema(tags=TAG, summary="Catalogue des offices", responses=OfficeTypeOutputSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(OfficeTypeOutputSerializer(selectors_offices.office_type_list(), many=True).data)


class AssignmentListCreateApi(AuthedV1Api):
    @extend_schema(
        tags=TAG,
        operation_id="hierarchy_assignments_list",
        summary=(
            "Nominations visibles : celles des nœuds où j'ai offices.nommer, en lecture celles des nœuds "
            "où j'ai tableau_bord.voir, et les miennes"
        ),
        parameters=[AssignmentFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(AssignmentOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = AssignmentFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=AssignmentOutputSerializer,
            queryset=selectors_offices.assignment_list(actor=request.user, filters=filters.validated_data),
            request=request,
            view=self,
        )

    @extend_schema(
        tags=TAG,
        summary="Nommer une personne à un office (offices.nommer + office « nommeur »)",
        request=AssignmentCreateInputSerializer,
        responses={201: AssignmentOutputSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = AssignmentCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        assignment = services_offices.assignment_create(
            actor=request.user,
            person=selectors_offices.person_get(person_id=data["person_id"]),
            office_type=selectors_offices.office_type_get_by_code(code=data["office"]),
            node=selectors.node_get(node_id=data["node_id"]),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            decree_ref=data["decree_ref"],
            note=data["note"],
            ip=_ip(request),
        )
        return Response(AssignmentOutputSerializer(assignment).data, status=status.HTTP_201_CREATED)


class AssignmentDetailApi(AuthedV1Api):
    def _get_visible(self, request: Request, assignment_id: int):
        assignment = selectors_offices.assignment_get(assignment_id=assignment_id)
        visible = (
            assignment.person_id == request.user.pk
            or authz.peut(request.user, "offices.nommer", assignment.node)
            or authz.peut(request.user, "tableau_bord.voir", assignment.node)
        )
        if not visible:
            raise NotFoundError("Nomination introuvable.", {"assignment_id": assignment_id})
        return assignment

    @extend_schema(tags=TAG, summary="Détail d'une nomination", responses=AssignmentOutputSerializer)
    def get(self, request: Request, assignment_id: int) -> Response:
        return Response(AssignmentOutputSerializer(self._get_visible(request, assignment_id)).data)

    @extend_schema(
        tags=TAG,
        summary="Terminer ou annuler une nomination",
        request=AssignmentUpdateInputSerializer,
        responses=AssignmentOutputSerializer,
    )
    def patch(self, request: Request, assignment_id: int) -> Response:
        assignment = self._get_visible(request, assignment_id)
        serializer = AssignmentUpdateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data["action"] == "terminer":
            assignment = services_offices.assignment_terminate(
                actor=request.user, assignment=assignment, end_date=serializer.validated_data.get("end_date"), ip=_ip(request)
            )
        else:
            assignment = services_offices.assignment_cancel(actor=request.user, assignment=assignment, ip=_ip(request))
        return Response(AssignmentOutputSerializer(assignment).data)


class PersonSearchApi(AuthedV1Api):
    permission_classes = (IsAuthenticated, _StaffMfa, HasCapability("offices.nommer"))

    @extend_schema(
        tags=TAG,
        operation_id="hierarchy_persons_list",
        summary="Rechercher la personne à nommer (offices.nommer ; e-mail masqué)",
        parameters=[PersonSearchFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(PersonSearchOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = PersonSearchFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=PersonSearchOutputSerializer,
            queryset=selectors_offices.person_search(q=filters.validated_data["q"]),
            request=request,
            view=self,
        )


class AssignmentImportApi(AuthedV1Api):
    permission_classes = (IsAuthenticated, _StaffMfa, HasCapability("offices.nommer"))
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(
        tags=TAG,
        summary="Importer le mouvement annuel des affectations (CSV : action, email, office, node_code…)",
        parameters=[AssignmentImportQuerySerializer],
        request={"multipart/form-data": ImportInputSerializer},
        responses=ImportReportSerializer,
    )
    def post(self, request: Request) -> Response:
        query = AssignmentImportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        serializer = ImportInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            content = serializer.validated_data["file"].read().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ApplicationError("Le fichier doit être encodé en UTF-8.", code="csv_encoding") from exc
        report = assignments_import_csv(
            actor=request.user,
            content=content,
            effective_date=query.validated_data["effective_date"],
            dry_run=query.validated_data["dry_run"],
        )
        return Response(ImportReportSerializer(report.as_dict()).data)


# --- Vérification de l'état de vie ------------------------------------------------------


def _person_status(person: Any) -> dict[str, Any]:
    return PersonStatusOutputSerializer(person).data


class VerificationListApi(AuthedV1Api):
    permission_classes = (IsAuthenticated, _StaffMfa, HasCapability("personnes.verifier"))

    @extend_schema(
        tags=TAG,
        summary="Déclarations d'état de vie à vérifier ou en attente de complément (personnes.verifier)",
        parameters=[VerificationFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(PersonStatusOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = VerificationFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        queryset = selectors_offices.verification_queue(actor=request.user)
        if statut := filters.validated_data.get("statut"):
            queryset = queryset.filter(statut_verification=statut)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=PersonStatusOutputSerializer,
            queryset=queryset,
            request=request,
            view=self,
        )


class VerificationDecisionApi(AuthedV1Api):
    permission_classes = (IsAuthenticated, _StaffMfa, HasCapability("personnes.verifier"))

    @extend_schema(
        tags=TAG,
        summary="Vérifier, rejeter ou demander un complément (personnes.verifier sur l'incardination)",
        request=VerificationDecisionInputSerializer,
        responses=PersonStatusOutputSerializer,
    )
    def post(self, request: Request, person_id: str) -> Response:
        serializer = VerificationDecisionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = selectors_offices.person_get(person_id=person_id)
        # Hors de mon périmètre, la personne « n'existe pas » : on ne révèle pas son statut.
        if not selectors_offices.verification_queue(actor=request.user).filter(pk=target.pk).exists():
            raise NotFoundError("Déclaration introuvable.", {"person_id": str(person_id)})
        person = services_offices.person_verification_decide(
            actor=request.user, person=target, ip=_ip(request), **serializer.validated_data
        )
        return Response(_person_status(selectors_offices.person_get(person_id=person.pk)))


# --- Retraits de capacités (plateforme) --------------------------------------------------


class CapabilityOverrideListCreateApi(AuthedV1Api):
    permission_classes = (IsAuthenticated, _StaffMfa, HasCapability("plateforme.admin"))

    @extend_schema(tags=TAG, summary="Retraits de capacités par diocèse", responses=CapabilityOverrideSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(CapabilityOverrideSerializer(selectors_offices.capability_override_list(), many=True).data)

    @extend_schema(
        tags=TAG,
        summary="Retirer une capacité à un office dans un diocèse (plateforme.admin)",
        request=CapabilityOverrideSerializer,
        responses={201: CapabilityOverrideSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = CapabilityOverrideSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        capability = Capability.objects.filter(code=data["capability"]["code"]).first()
        if capability is None:
            raise NotFoundError("Capacité inconnue.", {"capability": data["capability"]["code"]})
        override = services_offices.capability_override_create(
            actor=request.user,
            diocese_node=selectors.node_get(node_id=data["diocese_node_id"]),
            office_type=selectors_offices.office_type_get_by_code(code=data["office_type"]["code"]),
            capability=capability,
        )
        return Response(CapabilityOverrideSerializer(override).data, status=status.HTTP_201_CREATED)


class CapabilityOverrideDeleteApi(AuthedV1Api):
    permission_classes = (IsAuthenticated, _StaffMfa, HasCapability("plateforme.admin"))

    @extend_schema(tags=TAG, summary="Annuler un retrait de capacité (plateforme.admin)", responses={204: None})
    def delete(self, request: Request, override_id: int) -> Response:
        override = CapabilityOverride.objects.filter(pk=override_id).first()
        if override is None:
            raise NotFoundError("Retrait introuvable.", {"override_id": override_id})
        services_offices.capability_override_delete(actor=request.user, override=override)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Moi --------------------------------------------------------------------------------


class MeCapacitesApi(AuthedV1Api):
    @extend_schema(
        tags=ME_TAG,
        summary="Mes capacités et les nœuds où elles s'exercent (pour adapter l'interface)",
        responses=CapaciteOutputSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        return Response(CapaciteOutputSerializer(authz.capacites(request.user), many=True).data)


class MeDeclarationApi(AuthedV1Api):
    @extend_schema(tags=ME_TAG, summary="Mon état de vie déclaré", responses=PersonStatusOutputSerializer)
    def get(self, request: Request) -> Response:
        return Response(_person_status(selectors_offices.person_get(person_id=request.user.pk)))

    @extend_schema(
        tags=ME_TAG,
        summary=(
            "Déclarer ou compléter mon état de vie (reste « déclaré » jusqu'à vérification ; aucun effet "
            "sur les droits). Les justificatifs s'ajoutent aux précédents."
        ),
        request=DeclarationInputSerializer,
        responses=PersonStatusOutputSerializer,
    )
    def post(self, request: Request) -> Response:
        serializer = DeclarationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        incardination = data.get("incardination_node_id")
        institut = data.get("institut_node_id")
        person = services_offices.person_declaration_submit(
            person=request.user,
            etat_de_vie=data["etat_de_vie"],
            degre_ordre=data["degre_ordre"],
            incardination_node=selectors.node_get(node_id=incardination) if incardination else None,
            institut_node=selectors.node_get(node_id=institut) if institut else None,
            attachment_file_ids=data["attachment_file_ids"],
        )
        return Response(_person_status(selectors_offices.person_get(person_id=person.pk)))


# --- Journal d'audit -------------------------------------------------------------------


class AuditListApi(AuthedV1Api):
    permission_classes = (IsAuthenticated, _StaffMfa, HasCapability("audit.voir"))

    @extend_schema(
        tags=AUDIT_TAG,
        operation_id="audit_events_list",
        summary="Journal d'audit (audit.voir sur un nœud, ou plateforme)",
        parameters=[AuditFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(AuditEventOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = AuditFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=AuditEventOutputSerializer,
            queryset=selectors_offices.audit_list(actor=request.user, filters=filters.validated_data),
            request=request,
            view=self,
        )


class ParoisseSuivieInputSerializer(serializers.Serializer):
    node_id = serializers.UUIDField(allow_null=True, help_text="Paroisse à suivre ; null pour ne plus en suivre")


class ParoisseSuivieOutputSerializer(serializers.Serializer):
    node = NodeRefSerializer(allow_null=True)


class MeParoisseSuivieApi(AuthedV1Api):
    @extend_schema(tags=ME_TAG, summary="Ma paroisse suivie", responses=ParoisseSuivieOutputSerializer)
    def get(self, request: Request) -> Response:
        person = selectors_offices.person_get(person_id=request.user.pk)
        return Response(ParoisseSuivieOutputSerializer({"node": person.paroisse_suivie}).data)

    @extend_schema(
        tags=ME_TAG,
        summary="Changer de paroisse suivie (libre, sans validation — RG-01)",
        request=ParoisseSuivieInputSerializer,
        responses=ParoisseSuivieOutputSerializer,
    )
    def put(self, request: Request) -> Response:
        serializer = ParoisseSuivieInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        node_id = serializer.validated_data["node_id"]
        node = selectors.node_get(node_id=node_id) if node_id else None
        person = services_offices.paroisse_suivie_set(person=request.user, node=node)
        return Response(ParoisseSuivieOutputSerializer({"node": person.paroisse_suivie}).data)
