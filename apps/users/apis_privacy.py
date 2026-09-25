from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin
from apps.api.v1 import V1ApiMixin
from apps.users import selectors_privacy, services_privacy
from apps.users.apis import UserMeDetailApi

TAG = ["Conformité"]


class ConsentInputSerializer(serializers.Serializer):
    version = serializers.CharField(max_length=20, help_text="Version des CGU et de la politique acceptée")


ConsentOutput = inline_serializer(
    "ConsentStatus",
    {
        "current_version": serializers.CharField(),
        "given_version": serializers.CharField(),
        "given_at": serializers.DateTimeField(allow_null=True),
        "required": serializers.BooleanField(),
    },
)


def _consent_status(user) -> dict:
    return {
        "current_version": settings.CONSENT_CURRENT_VERSION,
        "given_version": user.consent_version,
        "given_at": user.consent_at,
        "required": services_privacy.consent_required(user=user),
    }


class _ExportThrottle(UserRateThrottle):
    rate = "5/hour"


class MeConsentApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(tags=TAG, summary="État de mon consentement", responses=ConsentOutput)
    def get(self, request: Request) -> Response:
        return Response(_consent_status(request.user))

    @extend_schema(
        tags=TAG,
        summary="Donner mon consentement explicite (version en vigueur)",
        request=ConsentInputSerializer,
        responses=ConsentOutput,
    )
    def post(self, request: Request) -> Response:
        serializer = ConsentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services_privacy.consent_give(user=request.user, **serializer.validated_data)
        return Response(_consent_status(user))


class MeExportApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated,)
    throttle_classes = (_ExportThrottle,)

    @extend_schema(tags=TAG, summary="Exporter mes données personnelles (JSON)", responses=OpenApiTypes.OBJECT)
    def get(self, request: Request) -> Response:
        response = Response(selectors_privacy.personal_data_export(user=request.user))
        response["Content-Disposition"] = 'attachment; filename="jangubi-mes-donnees.json"'
        response["Cache-Control"] = "no-store"
        return response


class MeApi(V1ApiMixin, UserMeDetailApi):
    """/me/ : profil (GET) et suppression du compte (DELETE, EF-CONF-03)."""

    @extend_schema(
        tags=TAG,
        summary="Supprimer mon compte (anonymisation, purge des conversations ; irréversible)",
        responses={
            204: None,
            400: OpenApiResponse(description="Compte déjà supprimé"),
            409: OpenApiResponse(description="Nomination en cours : elle doit d'abord prendre fin"),
        },
    )
    def delete(self, request: Request) -> Response:
        services_privacy.account_delete(user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
