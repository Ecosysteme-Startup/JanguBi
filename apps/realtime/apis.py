"""Flux SSE des tableaux de bord des dons : ``GET /api/v1/staff/dons/flux/?noeud=<id>``.

La vue est synchrone (DRF : authentification, droits, format d'erreur V1) ; elle renvoie un
``StreamingHttpResponse`` sur un générateur asynchrone, que Django sert au fil de l'eau sous
ASGI (Daphne). Sous WSGI (gunicorn), le flux ne fonctionne pas : il faut Daphne.
"""

import json
from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin
from apps.api.v1 import V1ApiMixin
from apps.hierarchy import selectors as hierarchy_selectors
from apps.realtime.dons import dons_flux_check, dons_resync, stream_for
from apps.realtime.sse import sse_release_db_connection, sse_response, sse_stream


class EventStreamRenderer(BaseRenderer):
    """Négociation de ``Accept: text/event-stream`` ; les erreurs (401, 403) restent en JSON."""

    media_type = "text/event-stream"
    format = "sse"
    charset = "utf-8"

    def render(self, data: Any, accepted_media_type: str | None = None, renderer_context: Any = None) -> bytes:
        return json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else b""


class SseTicketAuthentication(BaseAuthentication):
    """``?ticket=`` : ticket à usage unique de ``POST /me/ws-ticket/``, pour ``EventSource``
    natif qui ne sait pas poser d'en-tête. Chaque reconnexion demande un nouveau ticket."""

    def authenticate(self, request: Any) -> tuple[Any, None] | None:
        from apps.authentication.ws_tickets import ws_ticket_consume

        ticket = request.query_params.get("ticket")
        if not ticket:
            return None
        user = ws_ticket_consume(ticket=ticket)
        if user is None:
            from rest_framework.exceptions import AuthenticationFailed

            raise AuthenticationFailed("Ticket invalide ou expiré.", code="invalid_ticket")
        return user, None


class DonsFluxQuerySerializer(serializers.Serializer):
    noeud = serializers.UUIDField(help_text="Paroisse (flux complet) ou diocèse (invalidations seulement).")


class DonsFluxApi(V1ApiMixin, ApiAuthMixin, APIView):
    """Hors ATOMIC_REQUESTS : lectures seules, et la connexion est rendue avant le flux."""

    authentication_classes = [*ApiAuthMixin.authentication_classes, SseTicketAuthentication]
    permission_classes = (IsAuthenticated,)
    renderer_classes = [EventStreamRenderer, JSONRenderer]

    @extend_schema(
        tags=["dons"],
        operation_id="staff_dons_flux",
        summary="Flux SSE des tableaux de bord (dons.operation, dons.synthese_invalidee)",
        description=(
            "text/event-stream. Battement « : ping » toutes les 15 s, champ retry, reprise par "
            "l'en-tête Last-Event-ID. Protocole : docs/TEMPS-REEL.md."
        ),
        parameters=[
            DonsFluxQuerySerializer,
            OpenApiParameter("ticket", str, description="Ticket à usage unique (EventSource natif)"),
            OpenApiParameter("Last-Event-ID", str, location=OpenApiParameter.HEADER, required=False),
        ],
        responses={200: OpenApiResponse(response=OpenApiTypes.STR, description="text/event-stream")},
    )
    def get(self, request: Request) -> Any:
        query = DonsFluxQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        node = hierarchy_selectors.node_get(node_id=query.validated_data["noeud"])
        dons_flux_check(user=request.user, node=node)
        node_id = node.pk
        last_event_id = request.META.get("HTTP_LAST_EVENT_ID") or request.query_params.get("lastEventId")
        sse_release_db_connection()
        return sse_response(
            sse_stream(stream=stream_for(node.pk), last_event_id=last_event_id, resync=lambda: dons_resync(node_id))
        )
