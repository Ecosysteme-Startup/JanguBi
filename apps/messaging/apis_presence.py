"""Présence dans la messagerie (docs/TEMPS-REEL.md) : lecture et réglage « montrer ma présence »."""

from typing import Any

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin
from apps.api.v1 import V1ApiMixin
from apps.messaging.selectors_presence import presence_for
from apps.messaging.services_presence import presence_default_for, presence_setting_update, presence_visible


class PresenceQuerySerializer(serializers.Serializer):
    users = serializers.CharField(help_text="Identifiants séparés par des virgules (50 au plus).")

    def validate_users(self, value: str) -> list[str]:
        from django.conf import settings

        ids = [v.strip() for v in value.split(",") if v.strip()]
        if not ids:
            raise serializers.ValidationError("Au moins un identifiant.")
        if len(ids) > settings.PRESENCE_MAX_USERS_PER_QUERY:
            raise serializers.ValidationError(f"{settings.PRESENCE_MAX_USERS_PER_QUERY} identifiants au plus.")
        field = serializers.UUIDField()
        return [str(field.to_internal_value(v)) for v in ids]


class PresenceOutputSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    visible = serializers.BooleanField(help_text="Faux : la personne ne montre pas sa présence.")
    online = serializers.BooleanField(allow_null=True)
    last_seen_at = serializers.DateTimeField(allow_null=True, help_text="« Vu à », seulement hors ligne.")


class PresenceSettingSerializer(serializers.Serializer):
    montrer_presence = serializers.BooleanField(
        allow_null=True,
        help_text="null : revenir au réglage par défaut (oui pour le clergé et le staff). Réciproque : "
        "si vous masquez votre présence, vous ne verrez plus celle des autres.",
    )
    effective = serializers.BooleanField(read_only=True)
    default = serializers.BooleanField(read_only=True)


def _setting_data(user) -> dict:
    return {
        "montrer_presence": user.montrer_presence,
        "effective": presence_visible(user),
        "default": presence_default_for(user),
    }


class PresenceApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=["messaging"],
        operation_id="messaging_presence",
        summary="Présence de mes interlocuteurs (en ligne, vu à) ; les autres identifiants sont ignorés ; "
        "tout est « inconnu » si je masque ma propre présence",
        parameters=[OpenApiParameter("users", str, required=True, description="UUID séparés par des virgules")],
        responses=PresenceOutputSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        query = PresenceQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        viewer: Any = request.user
        rows = presence_for(viewer=viewer, user_ids=query.validated_data["users"])
        return Response(PresenceOutputSerializer(rows, many=True).data)


class PresenceSettingApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=["me"],
        operation_id="me_presence_get",
        summary="Mon réglage « montrer ma présence »",
        responses=PresenceSettingSerializer,
    )
    def get(self, request: Request) -> Response:
        return Response(PresenceSettingSerializer(_setting_data(request.user)).data)

    @extend_schema(
        tags=["me"],
        operation_id="me_presence_update",
        summary="Changer mon réglage « montrer ma présence »",
        request=PresenceSettingSerializer,
        responses=PresenceSettingSerializer,
    )
    def put(self, request: Request) -> Response:
        serializer = PresenceSettingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        current: Any = request.user
        user = presence_setting_update(user=current, montrer_presence=serializer.validated_data["montrer_presence"])
        return Response(PresenceSettingSerializer(_setting_data(user)).data)
