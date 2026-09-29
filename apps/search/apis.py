"""Recherche transverse (lot V1-routes, B03) : couche HTTP."""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin
from apps.api.v1 import V1ApiMixin
from apps.core.exceptions import ApplicationError
from apps.search import selectors

TAG = ["search"]


class SearchQuerySerializer(serializers.Serializer):
    q = serializers.CharField(max_length=200, help_text="Au moins 2 caractères (3 pour la Bible)")
    types = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=f"Liste séparée par des virgules parmi {', '.join(selectors.TYPES)} (défaut : tous)",
    )
    limit = serializers.IntegerField(min_value=1, max_value=20, default=5, help_text="Résultats par type")
    offset = serializers.IntegerField(min_value=0, max_value=selectors.MAX_OFFSET, default=0, help_text="Décalage par type")

    def validate_types(self, value: str) -> list[str]:
        types = [t.strip() for t in (value or "").split(",") if t.strip()]
        unknown = [t for t in types if t not in selectors.TYPES]
        if unknown:
            raise serializers.ValidationError(f"Types inconnus : {', '.join(unknown)}.")
        return list(dict.fromkeys(types)) or list(selectors.TYPES)


class _TypeResultSerializer(serializers.Serializer):
    items = serializers.ListField(child=serializers.DictField())
    next_offset = serializers.IntegerField(allow_null=True, help_text="null : pas de page suivante pour ce type")


class SearchOutputSerializer(serializers.Serializer):
    q = serializers.CharField()
    results = serializers.DictField(child=_TypeResultSerializer(), help_text="Une entrée par type demandé")


class SearchApi(V1ApiMixin, ApiAuthMixin, APIView):
    """Publique ; connecté, les prêtres joignables et la sonothèque réservée à mes paroisses
    s'ajoutent aux résultats."""

    permission_classes = (AllowAny,)

    @extend_schema(
        tags=TAG,
        operation_id="search",
        summary="Recherche transverse : Bible, paroisses, lieux, annonces, prêtres joignables, sonothèque",
        parameters=[SearchQuerySerializer],
        responses=SearchOutputSerializer,
    )
    def get(self, request: Request) -> Response:
        query = SearchQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        if len(data["q"].strip()) < selectors.MIN_LENGTH:
            raise ApplicationError("Tapez au moins deux caractères.", code="recherche_trop_courte")
        types = data.get("types") or list(selectors.TYPES)
        result = selectors.search(
            user=request.user, q=data["q"], types=types, offset=data["offset"], limit=data["limit"]
        )
        return Response(SearchOutputSerializer(result).data)
