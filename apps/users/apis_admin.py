"""Administration des comptes synchronisée avec Keycloak (docs/ADMIN-KEYCLOAK.md).

Préfixe ``/api/v1/admin/``. Capacité ``comptes.gerer`` (MFA exigée) ; la portée fine de chaque
compte est contrôlée par les services (plateforme > diocèse > paroisse, jamais au-dessus).
"""

import csv
import io
from collections.abc import Callable
from typing import Any, cast

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin
from apps.api.pagination import LimitOffsetPagination, paginated_response_serializer
from apps.api.v1 import V1ApiMixin
from apps.core.exceptions import ApplicationError, NotFoundError
from apps.core.request_context import client_ip
from apps.hierarchy import authz
from apps.hierarchy.enums import DegreOrdre, EtatDeVie
from apps.hierarchy.models import Node, OfficeAssignment, OfficeType
from apps.integrations.keycloak.client import REQUIRED_ACTIONS
from apps.users import scope_admin, selectors_admin, services_admin
from apps.users.services_keycloak_sync import keycloak_reconcile

TAG = ["admin-comptes"]
_PAGINATION = [
    OpenApiParameter("limit", int, description="Nombre de résultats (défaut 10, max 50)"),
    OpenApiParameter("offset", int, description="Décalage"),
]
_KC_ERRORS = {
    403: OpenApiResponse(description="Hors de votre portée (ou action réservée à la plateforme)"),
    409: OpenApiResponse(description="Conflit (e-mail pris, compte non lié, dernier administrateur…)"),
    503: OpenApiResponse(description="Keycloak injoignable : rien n'a été modifié"),
}


def _ip(request: Request) -> str | None:
    return client_ip(request.META)


class _AdminApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated, authz.HasCapability("comptes.gerer"))


def _node(node_id: Any) -> Node:
    node = Node.objects.filter(pk=node_id).first()
    if node is None:
        raise NotFoundError("Nœud introuvable.", {"node_id": str(node_id)})
    return node


# --- Sérialiseurs -----------------------------------------------------------------------------


class AdminNodeRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class AdminAccountFilterSerializer(serializers.Serializer):
    q = serializers.CharField(
        required=False, allow_blank=True, max_length=100, help_text="E-mail, prénom, nom, téléphone"
    )
    status = serializers.ChoiceField(choices=selectors_admin.STATUSES, required=False)
    role = serializers.ChoiceField(choices=selectors_admin.ROLES, required=False)
    sync = serializers.ChoiceField(
        choices=selectors_admin.SYNC_STATES, required=False, help_text="État de synchronisation"
    )
    etat_de_vie = serializers.ChoiceField(choices=EtatDeVie.choices, required=False)
    node = serializers.UUIDField(required=False, help_text="Comptes rattachés à ce nœud ou à son sous-arbre")
    created_from = serializers.DateField(required=False)
    created_to = serializers.DateField(required=False)
    ordering = serializers.ChoiceField(choices=tuple(selectors_admin.ORDERINGS), required=False)


class AdminAccountOutputSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    full_name = serializers.CharField()
    phone_number = serializers.CharField(allow_null=True)
    status = serializers.ChoiceField(choices=selectors_admin.STATUSES)
    role = serializers.ChoiceField(choices=selectors_admin.ROLES)
    etat_de_vie = serializers.ChoiceField(choices=EtatDeVie.choices)
    email_verified = serializers.BooleanField()
    keycloak_id = serializers.CharField(allow_null=True)
    sync = serializers.ChoiceField(choices=selectors_admin.SYNC_STATES)
    sync_error = serializers.CharField(allow_null=True)
    synced_at = serializers.DateTimeField(allow_null=True)
    admin_node = AdminNodeRefSerializer(allow_null=True)
    created_at = serializers.DateTimeField()
    last_login = serializers.DateTimeField(allow_null=True)
    last_seen_on = serializers.DateField(allow_null=True)
    can_manage = serializers.BooleanField(help_text="L'acteur peut agir sur ce compte (portée)")


class AdminOfficeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    office = serializers.CharField()
    office_label = serializers.CharField()
    node = AdminNodeRefSerializer()
    status = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField(allow_null=True)


class KeycloakSessionSerializer(serializers.Serializer):
    id = serializers.CharField()
    ip = serializers.CharField(allow_null=True)
    started_at = serializers.DateTimeField(allow_null=True)
    last_access = serializers.DateTimeField(allow_null=True)
    clients = serializers.ListField(child=serializers.CharField())


class KeycloakStateSerializer(serializers.Serializer):
    available = serializers.BooleanField(help_text="Faux : Keycloak injoignable, état inconnu")
    exists = serializers.BooleanField(required=False)
    enabled = serializers.BooleanField(required=False)
    email_verified = serializers.BooleanField(required=False)
    required_actions = serializers.ListField(child=serializers.CharField(), required=False)
    otp = serializers.BooleanField(required=False)
    webauthn = serializers.BooleanField(required=False)
    password = serializers.BooleanField(required=False)
    realm_roles = serializers.ListField(child=serializers.CharField(), required=False)
    groups = serializers.ListField(child=serializers.CharField(), required=False)
    locked_by_brute_force = serializers.BooleanField(required=False)
    failed_logins = serializers.IntegerField(required=False)
    sessions = KeycloakSessionSerializer(many=True, required=False)


class AdminAccountDetailSerializer(AdminAccountOutputSerializer):
    statut_verification = serializers.CharField()
    degre_ordre = serializers.CharField()
    offices = AdminOfficeSerializer(many=True)
    scope_nodes = AdminNodeRefSerializer(many=True)
    keycloak = KeycloakStateSerializer(allow_null=True, help_text="État en direct dans Keycloak ; null si non lié")


class AdminAccountCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True, allow_null=True)
    node_id = serializers.UUIDField(help_text="Nœud gestionnaire du compte (dans votre périmètre)")
    etat_de_vie = serializers.ChoiceField(choices=EtatDeVie.choices, default=EtatDeVie.LAIC)
    degre_ordre = serializers.ChoiceField(choices=DegreOrdre.choices, default=DegreOrdre.AUCUN)
    send_invitation = serializers.BooleanField(
        default=True, help_text="Keycloak envoie le lien : vérifier l'e-mail et choisir un mot de passe"
    )


class AdminAccountUpdateSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    first_name = serializers.CharField(max_length=50, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=50, required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True, allow_null=True)
    admin_node_id = serializers.UUIDField(required=False, allow_null=True)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, help_text="Motif (journalisé)")


class OptionalReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class DeleteSerializer(ReasonSerializer):
    confirm_email = serializers.EmailField(help_text="Adresse du compte, recopiée pour confirmer")


class ActionsEmailSerializer(serializers.Serializer):
    actions = serializers.ListField(child=serializers.ChoiceField(choices=REQUIRED_ACTIONS), min_length=1)


class PlatformAdminSerializer(ReasonSerializer):
    grant = serializers.BooleanField(help_text="Vrai : donner le rôle ; faux : le retirer")


class OfficeAssignSerializer(serializers.Serializer):
    office_type = serializers.CharField(help_text="Code de l'office (catalogue)")
    node_id = serializers.UUIDField()
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False, allow_null=True)
    quality = serializers.CharField(required=False, allow_blank=True, default="")
    decree_ref = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)


class OfficeEndSerializer(serializers.Serializer):
    end_date = serializers.DateField(required=False)


# --- Comptes ----------------------------------------------------------------------------------


def _row(request: Request, account: Any) -> dict[str, Any]:
    return AdminAccountOutputSerializer(selectors_admin.admin_account_row(actor=request.user, user=account)).data


class AdminAccountListCreateApi(_AdminApi):
    @extend_schema(
        tags=TAG,
        operation_id="admin_accounts_list",
        summary="Comptes de mon périmètre (recherche, filtres)",
        parameters=[AdminAccountFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(AdminAccountOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = AdminAccountFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        paginator = LimitOffsetPagination()
        page = paginator.paginate_queryset(
            selectors_admin.admin_account_list(actor=request.user, filters=filters.validated_data), request, view=self
        )
        rows = [selectors_admin.admin_account_row(actor=request.user, user=u) for u in page or []]
        return paginator.get_paginated_response(AdminAccountOutputSerializer(rows, many=True).data)

    @extend_schema(
        tags=TAG,
        operation_id="admin_accounts_create",
        summary="Créer un compte (Keycloak + application) et envoyer l'invitation",
        request=AdminAccountCreateSerializer,
        responses={201: AdminAccountOutputSerializer, **_KC_ERRORS},
    )
    def post(self, request: Request) -> Response:
        data = AdminAccountCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        account = services_admin.account_admin_create(
            actor=request.user,
            email=v["email"],
            node=_node(v["node_id"]),
            first_name=v["first_name"],
            last_name=v["last_name"],
            phone_number=v.get("phone_number") or None,
            etat_de_vie=v["etat_de_vie"],
            degre_ordre=v["degre_ordre"],
            send_invitation=v["send_invitation"],
            ip=_ip(request),
        )
        account = selectors_admin.admin_account_get(actor=request.user, account_id=account.pk)
        return Response(_row(request, account), status=status.HTTP_201_CREATED)


class AdminAccountDetailApi(_AdminApi):
    @extend_schema(
        tags=TAG,
        operation_id="admin_accounts_retrieve",
        summary="Fiche d'un compte, avec son état en direct dans Keycloak",
        responses=AdminAccountDetailSerializer,
    )
    def get(self, request: Request, account_id: str) -> Response:
        account = selectors_admin.admin_account_get(actor=request.user, account_id=account_id)
        keycloak = (
            selectors_admin.keycloak_account_state(user=account)
            if scope_admin.can_manage(request.user, account)
            else None
        )
        detail = selectors_admin.admin_account_detail(actor=request.user, user=account, keycloak=keycloak)
        return Response(AdminAccountDetailSerializer(detail).data)

    @extend_schema(
        tags=TAG,
        operation_id="admin_accounts_update",
        summary="Modifier l'identité d'un compte (répercuté dans Keycloak)",
        request=AdminAccountUpdateSerializer,
        responses={200: AdminAccountOutputSerializer, **_KC_ERRORS},
    )
    def patch(self, request: Request, account_id: str) -> Response:
        account = selectors_admin.admin_account_get(actor=request.user, account_id=account_id)
        data = AdminAccountUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        if "admin_node_id" in values:
            node_id = values.pop("admin_node_id")
            values["admin_node"] = _node(node_id) if node_id else None
        services_admin.account_admin_update(actor=request.user, account=account, data=values, ip=_ip(request))
        return Response(_row(request, selectors_admin.admin_account_get(actor=request.user, account_id=account_id)))

    @extend_schema(
        tags=TAG,
        operation_id="admin_accounts_destroy",
        summary="Supprimer un compte (RGPD : anonymisation + suppression Keycloak)",
        request=DeleteSerializer,
        responses={204: None, **_KC_ERRORS},
    )
    def delete(self, request: Request, account_id: str) -> Response:
        account = selectors_admin.admin_account_get(actor=request.user, account_id=account_id)
        data = DeleteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services_admin.account_admin_delete(
            actor=request.user,
            account=account,
            confirm_email=data.validated_data["confirm_email"],
            reason=data.validated_data["reason"],
            ip=_ip(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


def _action(
    *,
    operation_id: str,
    summary: str,
    serializer: type[serializers.Serializer] | None,
    call: Callable[[Request, Any, dict[str, Any]], Any],
) -> type[_AdminApi]:
    class _ActionApi(_AdminApi):
        @extend_schema(
            tags=TAG,
            operation_id=operation_id,
            summary=summary,
            request=serializer,
            responses={200: AdminAccountOutputSerializer, **_KC_ERRORS},
        )
        def post(self, request: Request, account_id: str) -> Response:
            account = selectors_admin.admin_account_get(actor=request.user, account_id=account_id)
            values: dict[str, Any] = {}
            if serializer is not None:
                data = serializer(data=request.data)
                data.is_valid(raise_exception=True)
                values = dict(data.validated_data)
            call(request, account, values)
            return Response(_row(request, selectors_admin.admin_account_get(actor=request.user, account_id=account_id)))

    _ActionApi.__name__ = "".join(p.title() for p in operation_id.split("_")) + "Api"
    return _ActionApi


AdminAccountDisableApi = _action(
    operation_id="admin_accounts_disable",
    summary="Désactiver un compte (Keycloak désactivé, sessions fermées)",
    serializer=ReasonSerializer,
    call=lambda r, a, v: services_admin.account_admin_set_active(
        actor=r.user, account=a, active=False, reason=v["reason"], ip=_ip(r)
    ),
)
AdminAccountEnableApi = _action(
    operation_id="admin_accounts_enable",
    summary="Réactiver un compte (et lever un blocage anti-force brute)",
    serializer=OptionalReasonSerializer,
    call=lambda r, a, v: services_admin.account_admin_set_active(
        actor=r.user, account=a, active=True, reason=v.get("reason", ""), ip=_ip(r)
    ),
)
AdminAccountPasswordResetApi = _action(
    operation_id="admin_accounts_password_reset",
    summary="Envoyer le lien Keycloak de nouveau mot de passe",
    serializer=None,
    call=lambda r, a, v: services_admin.account_password_reset(actor=r.user, account=a, ip=_ip(r)),
)
AdminAccountActionsEmailApi = _action(
    operation_id="admin_accounts_actions_email",
    summary="Envoyer l'e-mail Keycloak d'actions requises",
    serializer=ActionsEmailSerializer,
    call=lambda r, a, v: services_admin.account_actions_email(actor=r.user, account=a, actions=v["actions"], ip=_ip(r)),
)
AdminAccountVerifyEmailApi = _action(
    operation_id="admin_accounts_verify_email",
    summary="Renvoyer l'e-mail de vérification de l'adresse",
    serializer=None,
    call=lambda r, a, v: services_admin.account_verify_email_send(actor=r.user, account=a, ip=_ip(r)),
)
AdminAccountMarkEmailVerifiedApi = _action(
    operation_id="admin_accounts_mark_email_verified",
    summary="Marquer l'adresse comme vérifiée (plateforme, motif obligatoire)",
    serializer=ReasonSerializer,
    call=lambda r, a, v: services_admin.account_email_mark_verified(
        actor=r.user, account=a, reason=v["reason"], ip=_ip(r)
    ),
)
AdminAccountLogoutApi = _action(
    operation_id="admin_accounts_logout",
    summary="Fermer toutes les sessions (jetons révoqués)",
    serializer=None,
    call=lambda r, a, v: services_admin.account_sessions_logout(actor=r.user, account=a, ip=_ip(r)),
)
AdminAccountOtpResetApi = _action(
    operation_id="admin_accounts_otp_reset",
    summary="Réinitialiser le second facteur (nouveau exigé à la connexion)",
    serializer=ReasonSerializer,
    call=lambda r, a, v: services_admin.account_otp_reset(actor=r.user, account=a, reason=v["reason"], ip=_ip(r)),
)
AdminAccountBruteForceUnlockApi = _action(
    operation_id="admin_accounts_brute_force_unlock",
    summary="Débloquer un compte bloqué après des échecs de connexion",
    serializer=None,
    call=lambda r, a, v: services_admin.account_brute_force_unlock(actor=r.user, account=a, ip=_ip(r)),
)
AdminAccountPlatformAdminApi = _action(
    operation_id="admin_accounts_platform_admin",
    summary="Donner ou retirer le rôle administrateur plateforme (plateforme seulement)",
    serializer=PlatformAdminSerializer,
    call=lambda r, a, v: services_admin.account_platform_admin_set(
        actor=r.user, account=a, grant=v["grant"], reason=v["reason"], ip=_ip(r)
    ),
)
AdminAccountResyncApi = _action(
    operation_id="admin_accounts_resync",
    summary="Resynchroniser le compte avec Keycloak",
    serializer=None,
    call=lambda r, a, v: services_admin.account_resync(actor=r.user, account=a, ip=_ip(r)),
)


class AdminAccountSessionsApi(_AdminApi):
    @extend_schema(
        tags=TAG,
        operation_id="admin_accounts_sessions",
        summary="Sessions ouvertes dans Keycloak",
        responses={200: KeycloakSessionSerializer(many=True), **_KC_ERRORS},
    )
    def get(self, request: Request, account_id: str) -> Response:
        account = selectors_admin.admin_account_get(actor=request.user, account_id=account_id)
        scope_admin.require_manage(request.user, account)
        state = selectors_admin.keycloak_account_state(user=account)
        if state is None or not state.get("available"):
            raise services_admin.KeycloakServiceError("État Keycloak indisponible pour ce compte.")
        return Response(KeycloakSessionSerializer(state.get("sessions", []), many=True).data)


class AdminAccountSessionRevokeApi(_AdminApi):
    @extend_schema(
        tags=TAG,
        operation_id="admin_accounts_session_revoke",
        summary="Fermer une session",
        responses={204: None, **_KC_ERRORS},
    )
    def delete(self, request: Request, account_id: str, session_id: str) -> Response:
        account = selectors_admin.admin_account_get(actor=request.user, account_id=account_id)
        services_admin.account_session_revoke(
            actor=request.user, account=account, session_id=session_id, ip=_ip(request)
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminAccountOfficeAssignApi(_AdminApi):
    @extend_schema(
        tags=TAG,
        operation_id="admin_accounts_office_assign",
        summary="Nommer le compte à un office (selon votre autorité de nomination)",
        request=OfficeAssignSerializer,
        responses={201: AdminOfficeSerializer, **_KC_ERRORS},
    )
    def post(self, request: Request, account_id: str) -> Response:
        from apps.hierarchy.services_offices import assignment_create

        account = selectors_admin.admin_account_get(actor=request.user, account_id=account_id)
        data = OfficeAssignSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        office_type = OfficeType.objects.filter(code=v["office_type"]).first()
        if office_type is None:
            raise ApplicationError("Office inconnu.", {"office_type": v["office_type"]}, code="office_unknown")
        assignment = assignment_create(
            actor=request.user,
            person=account,
            office_type=office_type,
            node=_node(v["node_id"]),
            start_date=v.get("start_date"),
            end_date=v.get("end_date"),
            quality=v["quality"],
            decree_ref=v["decree_ref"],
            ip=_ip(request),
        )
        return Response(AdminOfficeSerializer(_office_row(assignment)).data, status=status.HTTP_201_CREATED)


def _office_row(a: OfficeAssignment) -> dict[str, Any]:
    return {
        "id": a.pk,
        "office": a.office_type.code,
        "office_label": a.title,
        "node": {"id": a.node.pk, "name": a.node.name},
        "status": a.status,
        "start_date": a.start_date,
        "end_date": a.end_date,
    }


class AdminAccountOfficeEndApi(_AdminApi):
    @extend_schema(
        tags=TAG,
        operation_id="admin_accounts_office_end",
        summary="Mettre fin à une nomination du compte",
        request=OfficeEndSerializer,
        responses={200: AdminOfficeSerializer, **_KC_ERRORS},
    )
    def post(self, request: Request, account_id: str, assignment_id: int) -> Response:
        from apps.hierarchy.services_offices import assignment_terminate

        account = selectors_admin.admin_account_get(actor=request.user, account_id=account_id)
        assignment = (
            OfficeAssignment.objects.select_related("node", "office_type")
            .filter(pk=assignment_id, person=account)
            .first()
        )
        if assignment is None:
            raise NotFoundError("Nomination introuvable.", {"assignment_id": assignment_id})
        data = OfficeEndSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        assignment = assignment_terminate(
            actor=request.user, assignment=assignment, end_date=data.validated_data.get("end_date"), ip=_ip(request)
        )
        return Response(AdminOfficeSerializer(_office_row(assignment)).data)


class AdminAccountExportApi(_AdminApi):
    @extend_schema(
        tags=TAG,
        operation_id="admin_accounts_export",
        summary="Export CSV des comptes de mon périmètre (mêmes filtres que la liste)",
        parameters=[AdminAccountFilterSerializer],
        responses={(200, "text/csv"): OpenApiTypes.STR},
    )
    def get(self, request: Request) -> HttpResponse:
        filters = AdminAccountFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        buffer = io.StringIO()
        buffer.write("﻿")  # BOM : Excel lit l'UTF-8 correctement
        csv.writer(buffer, delimiter=";").writerows(
            selectors_admin.admin_export_rows(actor=request.user, filters=filters.validated_data)
        )
        from apps.hierarchy.audit import audit_log

        audit_log(
            actor=request.user,
            action="compte.admin.export",
            target=cast(Any, request.user),
            metadata=dict(request.query_params),
        )
        response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="comptes.csv"'
        return response


# --- Portée, journal, tableau de bord, synchronisation ---------------------------------------


class AdminScopeOutputSerializer(serializers.Serializer):
    is_platform_admin = serializers.BooleanField()
    nodes = AdminNodeRefSerializer(many=True, help_text="Nœuds où je gère les comptes (sous-arbres compris)")
    required_actions = serializers.ListField(child=serializers.CharField())
    impersonation = serializers.BooleanField(help_text="Toujours faux : l'usurpation d'identité n'est pas proposée")


class AdminScopeApi(_AdminApi):
    @extend_schema(
        tags=TAG,
        operation_id="admin_scope",
        summary="Mon périmètre d'administration",
        responses=AdminScopeOutputSerializer,
    )
    def get(self, request: Request) -> Response:
        grants = [g for g in authz.grants(request.user) if g.capability == scope_admin.CAPABILITY and g.node_id]
        nodes = {g.node_id: {"id": g.node_id, "name": g.node_name} for g in grants}
        return Response(
            AdminScopeOutputSerializer(
                {
                    "is_platform_admin": scope_admin.is_platform(request.user),
                    "nodes": list(nodes.values()),
                    "required_actions": list(REQUIRED_ACTIONS),
                    "impersonation": False,
                }
            ).data
        )


class AdminAuditFilterSerializer(serializers.Serializer):
    account = serializers.UUIDField(required=False, help_text="Compte visé")
    actor = serializers.UUIDField(required=False, help_text="Auteur de l'action")
    action = serializers.CharField(required=False, max_length=80, help_text="Préfixe (ex. compte.admin.)")
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)


class AdminAuditOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    at = serializers.DateTimeField()
    action = serializers.CharField()
    actor_id = serializers.UUIDField(allow_null=True)
    actor_email = serializers.CharField(allow_null=True)
    target_id = serializers.CharField()
    target_email = serializers.CharField(allow_null=True)
    node = AdminNodeRefSerializer(allow_null=True)
    metadata = serializers.JSONField()


class AdminAuditListApi(_AdminApi):
    @extend_schema(
        tags=TAG,
        operation_id="admin_audit_list",
        summary="Journal des actions sur les comptes (qui, quoi, quand, sur qui)",
        parameters=[AdminAuditFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(AdminAuditOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = AdminAuditFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        paginator = LimitOffsetPagination()
        page = (
            paginator.paginate_queryset(
                selectors_admin.admin_audit_list(actor=request.user, filters=filters.validated_data), request, view=self
            )
            or []
        )
        targets = selectors_admin.audit_targets(page)
        rows = [
            {
                "id": e.pk,
                "at": e.at,
                "action": e.action,
                "actor_id": e.actor_id,
                "actor_email": e.actor.email if e.actor else None,
                "target_id": e.target_id,
                "target_email": targets.get(e.target_id),
                "node": {"id": e.node.pk, "name": e.node.name} if e.node else None,
                "metadata": e.metadata,
            }
            for e in page
        ]
        return paginator.get_paginated_response(AdminAuditOutputSerializer(rows, many=True).data)


class DashboardCountsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    actifs = serializers.IntegerField()
    en_attente = serializers.IntegerField()
    desactives = serializers.IntegerField()
    responsables = serializers.IntegerField()
    administrateurs_plateforme = serializers.IntegerField()
    crees_30_jours = serializers.IntegerField()
    non_lies = serializers.IntegerField()
    ecarts = serializers.IntegerField()
    invitations_en_attente = serializers.IntegerField()


class DashboardSyncSerializer(serializers.Serializer):
    derniere_reconciliation = serializers.DateTimeField(allow_null=True)
    derniere_reconciliation_reussie = serializers.BooleanField(allow_null=True)
    ecarts_derniere_reconciliation = serializers.IntegerField(allow_null=True)


class AdminDashboardOutputSerializer(serializers.Serializer):
    comptes = DashboardCountsSerializer()
    synchronisation = DashboardSyncSerializer()


class AdminDashboardApi(_AdminApi):
    @extend_schema(
        tags=TAG,
        operation_id="admin_dashboard",
        summary="Tableau de bord des comptes",
        responses=AdminDashboardOutputSerializer,
    )
    def get(self, request: Request) -> Response:
        return Response(AdminDashboardOutputSerializer(selectors_admin.admin_dashboard(actor=request.user)).data)


class SyncRunSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    started_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField(allow_null=True)
    dry_run = serializers.BooleanField()
    trigger = serializers.CharField()
    success = serializers.BooleanField()
    error = serializers.CharField()
    counts = serializers.JSONField()


class SyncRunDetailSerializer(SyncRunSerializer):
    report = serializers.JSONField(help_text="Écarts : kind, keycloak_id, user_id, email (masqué), fields, correction")


class SyncEventsSerializer(serializers.Serializer):
    recus = serializers.IntegerField()
    echecs = serializers.IntegerField()
    traites_24h = serializers.IntegerField()
    dernier_recu = serializers.DateTimeField(allow_null=True)


class SyncCursorSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="utilisateur | admin")
    last_event_at = serializers.DateTimeField(allow_null=True)
    last_polled_at = serializers.DateTimeField(allow_null=True)
    last_error = serializers.CharField(allow_null=True)


class SyncStatusSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    events_polling = serializers.BooleanField(help_text="Lecture périodique des événements (Admin REST API)")
    webhook_enabled = serializers.BooleanField(help_text="Option webhook d'un SPI (désactivée par défaut)")
    curseurs = SyncCursorSerializer(many=True)
    comptes_non_lies = serializers.IntegerField()
    comptes_en_ecart = serializers.IntegerField()
    ecarts_par_type = serializers.DictField(child=serializers.IntegerField())
    evenements = SyncEventsSerializer()
    reconciliations = SyncRunSerializer(many=True)


class SyncRunInputSerializer(serializers.Serializer):
    dry_run = serializers.BooleanField(default=True, help_text="Vrai : rapport seulement, rien n'est corrigé")


class _PlatformAdminApi(_AdminApi):
    permission_classes = (IsAuthenticated, authz.HasCapability("plateforme.admin"))


class AdminSyncStatusApi(_PlatformAdminApi):
    @extend_schema(
        tags=TAG,
        operation_id="admin_sync_status",
        summary="État de la synchronisation Keycloak",
        responses=SyncStatusSerializer,
    )
    def get(self, request: Request) -> Response:
        return Response(SyncStatusSerializer(selectors_admin.sync_status()).data)


class AdminSyncRunCreateApi(_PlatformAdminApi):
    @extend_schema(
        tags=TAG,
        operation_id="admin_sync_run",
        summary="Lancer une réconciliation (simulation par défaut)",
        request=SyncRunInputSerializer,
        responses={201: SyncRunDetailSerializer},
    )
    def post(self, request: Request) -> Response:
        data = SyncRunInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        run = keycloak_reconcile(dry_run=data.validated_data["dry_run"], trigger="admin", actor=request.user)
        from apps.hierarchy.audit import audit_log

        audit_log(
            actor=request.user, action="compte.admin.reconciliation", target=run, metadata={"simulation": run.dry_run}
        )
        return Response(SyncRunDetailSerializer(run).data, status=status.HTTP_201_CREATED)


class AdminSyncRunDetailApi(_PlatformAdminApi):
    @extend_schema(
        tags=TAG,
        operation_id="admin_sync_run_retrieve",
        summary="Rapport d'une réconciliation",
        responses=SyncRunDetailSerializer,
    )
    def get(self, request: Request, run_id: int) -> Response:
        return Response(SyncRunDetailSerializer(selectors_admin.sync_run_get(run_id=run_id)).data)
