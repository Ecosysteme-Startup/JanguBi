from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin
from apps.api.v1 import V1ApiMixin
from apps.messaging.models import NotificationPreference
from apps.messaging.services_notifications import preferences_get, preferences_update


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ["in_app", "email", "push", "topic_annonces", "topic_evenements", "quiet_start", "quiet_end"]


class NotificationPreferenceApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(tags=["me"], summary="Mes préférences de notification", responses=NotificationPreferenceSerializer)
    def get(self, request: Request) -> Response:
        return Response(NotificationPreferenceSerializer(preferences_get(user=request.user)).data)

    @extend_schema(
        tags=["me"],
        summary="Modifier mes préférences (canaux, sujets, plage de silence)",
        request=NotificationPreferenceSerializer,
        responses=NotificationPreferenceSerializer,
    )
    def put(self, request: Request) -> Response:
        serializer = NotificationPreferenceSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(NotificationPreferenceSerializer(preferences_update(user=request.user, data=serializer.validated_data)).data)
