"""Réception des événements Keycloak par webhook — OPTION désactivée par défaut
(``KEYCLOAK_WEBHOOK_ENABLED``) : elle suppose un SPI (p2-inc « keycloak-events ») que l'image
officielle de Keycloak n'embarque pas. Le mode normal est la lecture périodique des événements
par l'Admin REST API (``keycloak_events_poll``).

Signature : en-tête ``X-Keycloak-Signature`` = HMAC-SHA256 (hex) du corps brut avec
``KEYCLOAK_WEBHOOK_SECRET``. Idempotent sur l'``uid`` de l'événement. Voir docs/ADMIN-KEYCLOAK.md.
"""

import json

from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.v1 import V1ApiMixin
from apps.core.exceptions import ApplicationError, NotFoundError, PermissionDeniedError
from apps.users.services_keycloak_sync import keycloak_event_ingest, webhook_signature_valid

SIGNATURE_HEADER = "HTTP_X_KEYCLOAK_SIGNATURE"
MAX_BODY_BYTES = 256 * 1024


class KeycloakWebhookApi(V1ApiMixin, APIView):
    authentication_classes: list = []
    permission_classes = (AllowAny,)

    @extend_schema(
        tags=["integrations"],
        operation_id="keycloak_events_receive",
        summary="Événement Keycloak signé (webhook du SPI d'événements)",
        request=inline_serializer(
            name="KeycloakWebhookEvent",
            fields={
                "uid": serializers.CharField(),
                "type": serializers.CharField(help_text="access.REGISTER, admin.USER-UPDATE…"),
                "userId": serializers.CharField(required=False),
                "resourcePath": serializers.CharField(required=False, help_text="users/<id>…"),
            },
        ),
        responses={
            202: inline_serializer(
                name="KeycloakWebhookAck", fields={"status": serializers.CharField(), "duplicate": serializers.BooleanField()}
            ),
            403: OpenApiResponse(description="Signature absente ou invalide"),
            404: OpenApiResponse(description="Webhook désactivé (KEYCLOAK_WEBHOOK_ENABLED)"),
        },
    )
    def post(self, request: Request) -> Response:
        from django.conf import settings

        if not settings.KEYCLOAK_WEBHOOK_ENABLED:
            raise NotFoundError("Webhook Keycloak désactivé.", code="webhook_disabled")
        body = request.body
        if len(body) > MAX_BODY_BYTES:
            raise ApplicationError("Événement trop volumineux.", code="payload_too_large")
        if not webhook_signature_valid(body=body, signature=request.META.get(SIGNATURE_HEADER, "")):
            raise PermissionDeniedError("Signature invalide.", code="invalid_signature")
        try:
            payload = json.loads(body or b"{}")
        except ValueError as exc:
            raise ApplicationError("Corps JSON invalide.", code="invalid_json") from exc
        events = payload if isinstance(payload, list) else [payload]
        duplicate = True
        last_status = "ignore"
        for item in events[:100]:
            if not isinstance(item, dict):
                continue
            event, created = keycloak_event_ingest(payload=item)
            duplicate = duplicate and not created
            last_status = event.status
        return Response({"status": last_status, "duplicate": duplicate}, status=status.HTTP_202_ACCEPTED)
