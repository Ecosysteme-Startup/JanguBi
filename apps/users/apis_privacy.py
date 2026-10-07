from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin
from apps.api.v1 import V1ApiMixin
from apps.users import selectors_privacy, services_privacy
from apps.users.enums import Title
from apps.users.services_me import me_profile_update

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

    @extend_schema(
        tags=TAG,
        summary="Retirer mon consentement « donnée sensible » (ferme et anonymise le compte ; irréversible)",
        responses={
            204: None,
            400: OpenApiResponse(description="Compte déjà supprimé"),
            409: OpenApiResponse(description="Nomination en cours : elle doit d'abord prendre fin"),
        },
    )
    def delete(self, request: Request) -> Response:
        services_privacy.consent_withdraw(user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeExportApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated,)
    throttle_classes = (_ExportThrottle,)

    @extend_schema(tags=TAG, summary="Exporter mes données personnelles (JSON)", responses=OpenApiTypes.OBJECT)
    def get(self, request: Request) -> Response:
        response = Response(selectors_privacy.personal_data_export(user=request.user))
        response["Content-Disposition"] = 'attachment; filename="jangubi-mes-donnees.json"'
        response["Cache-Control"] = "no-store"
        return response


class MeProfileSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=50, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=50, required=False, allow_blank=True)
    title = serializers.ChoiceField(choices=Title.choices, required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    phone = PhoneNumberField(required=False, allow_null=True)


class MeNodeRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class MeOutputSerializer(serializers.Serializer):
    """EF-PER-01. Les capacités s'obtiennent par /me/capacites/."""

    id = serializers.UUIDField()
    email = serializers.EmailField()
    profile = serializers.SerializerMethodField()
    etat_de_vie = serializers.CharField()
    degre_ordre = serializers.CharField()
    statut_verification = serializers.CharField()
    incardination = MeNodeRefSerializer(source="incardination_node", allow_null=True)
    institut = MeNodeRefSerializer(source="institut_node", allow_null=True)
    paroisse_suivie = MeNodeRefSerializer(allow_null=True)
    consent = serializers.SerializerMethodField()

    def get_profile(self, user) -> dict:
        profile = getattr(user, "profile", None)
        return {
            "first_name": getattr(profile, "first_name", ""),
            "last_name": getattr(profile, "last_name", ""),
            "title": getattr(profile, "title", ""),
            "date_of_birth": profile.date_of_birth.isoformat() if profile and profile.date_of_birth else None,
            "phone": str(profile.phone) if profile and profile.phone else None,
        }

    def get_consent(self, user) -> dict:
        return _consent_status(user)


class MeApi(V1ApiMixin, ApiAuthMixin, APIView):
    """/me/ : profil (GET, PATCH) et suppression du compte (DELETE, EF-CONF-03)."""

    permission_classes = (IsAuthenticated,)

    @extend_schema(tags=["Profil"], summary="Mon profil", responses=MeOutputSerializer)
    def get(self, request: Request) -> Response:
        return Response(MeOutputSerializer(request.user).data)

    @extend_schema(
        tags=["Profil"],
        summary="Modifier mon profil (e-mail et mot de passe : dans Keycloak)",
        request=MeProfileSerializer,
        responses=MeOutputSerializer,
    )
    def patch(self, request: Request) -> Response:
        serializer = MeProfileSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = me_profile_update(user=request.user, data=dict(serializer.validated_data))
        return Response(MeOutputSerializer(user).data)

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
