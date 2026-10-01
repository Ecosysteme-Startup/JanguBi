from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.contact.serializers import PresentationRequestInputSerializer, PresentationRequestOutputSerializer
from apps.contact.services import ContactValidationError, presentation_request_create
from apps.contact.throttling import ContactRateThrottle

TAG = ["public"]


class PublicContactApi(APIView):
    """Formulaire « Pour les paroisses ». Public : aucune authentification n'est lue."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (ContactRateThrottle,)

    @extend_schema(
        tags=TAG,
        operation_id="public_contact_create",
        summary="Demander une présentation de Jàngu Bi (formulaire « Pour les paroisses »)",
        request=PresentationRequestInputSerializer,
        responses={
            201: PresentationRequestOutputSerializer,
            400: OpenApiResponse(description="Erreurs par champ : { champ: [messages] }"),
            429: OpenApiResponse(description="Trop de demandes depuis cette adresse"),
        },
    )
    def post(self, request: Request) -> Response:
        serializer = PresentationRequestInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            presentation_request_create(**serializer.validated_data)
        except ContactValidationError as exc:
            return Response(
                {exc.extra.get("field", "non_field_errors"): [exc.message]}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(PresentationRequestOutputSerializer({"received": True}).data, status=status.HTTP_201_CREATED)
