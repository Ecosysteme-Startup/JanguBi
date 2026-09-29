"""Déclaration OpenAPI du ticket à usage unique des flux SSE (drf-spectacular)."""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class SseTicketScheme(OpenApiAuthenticationExtension):
    target_class = "apps.realtime.apis.SseTicketAuthentication"
    name = "sseTicket"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "query",
            "name": "ticket",
            "description": "Ticket à usage unique de POST /api/v1/me/ws-ticket/ (EventSource natif).",
        }
