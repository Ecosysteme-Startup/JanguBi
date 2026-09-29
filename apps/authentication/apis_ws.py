from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin
from apps.api.v1 import V1ApiMixin
from apps.authentication.ws_tickets import TICKET_TTL_SECONDS, ws_ticket_issue


class WsTicketApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        tags=["me"],
        summary="Ticket WebSocket à usage unique (60 s) : /ws/...?ticket=<ticket>",
        request=None,
        responses=inline_serializer(
            "WsTicketOutput", {"ticket": serializers.CharField(), "expires_in": serializers.IntegerField()}
        ),
    )
    def post(self, request: Request) -> Response:
        return Response({"ticket": ws_ticket_issue(user=request.user), "expires_in": TICKET_TTL_SECONDS})
