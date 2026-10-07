import datetime

from asgiref.sync import async_to_sync
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from drf_spectacular.openapi import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin
from apps.liturgy import selectors
from apps.liturgy.models import LiturgicalDate, Office
from apps.liturgy.serializers import (
    OfficeSerializer,
)
from apps.liturgy.services import AelfService


def user_can_access_hours(user) -> bool:
    """La Liturgie des Heures (gelée en V1) est réservée aux clercs et consacrés vérifiés."""
    from apps.hierarchy.persons import is_clerc_or_consecrated

    return is_clerc_or_consecrated(user)


class CanAccessLiturgyOfHours(IsAuthenticated):
    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        return user_can_access_hours(request.user)


# ---------------------------------------------------------------------------
# Base helpers
# ---------------------------------------------------------------------------


class _DailyLiturgyBase(ApiAuthMixin, APIView):
    """
    Common date/zone parsing and AELF auto-sync for liturgy endpoints.

    ApiAuthMixin est INDISPENSABLE : sans lui, le Bearer JWT n'était pas lu
    (pas de JWTAuthentication) et les endpoints clergé renvoyaient 401 à tout
    client SPA/mobile authentifié. Les vues publiques gardent AllowAny.
    """

    permission_classes = [AllowAny]

    def _get_params(self, request):
        date_str = request.query_params.get("date")
        zone = request.query_params.get("zone", "afrique")
        if not date_str:
            date_str = timezone.localtime().date().isoformat()
        return date_str, zone

    def _ensure_data(self, date_str, zone):
        try:
            target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return None, False

        exists = LiturgicalDate.objects.filter(date=target_date, zone=zone).exists()
        if not exists:
            async_to_sync(AelfService.sync_daily_data)(date_str, zone)

        date_obj = (
            LiturgicalDate.objects.filter(date=target_date, zone=zone)
            .prefetch_related("readings__matched_verses", "offices")
            .first()
        )
        return date_obj, True


class _OfficeBase(_DailyLiturgyBase):
    """Base for the 7 Liturgy of the Hours endpoints (clergy-only)."""

    permission_classes = [CanAccessLiturgyOfHours]
    office_type: str | None = None

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "date",
                OpenApiTypes.STR,
                description="Date YYYY-MM-DD (défaut: aujourd'hui)",
            ),
            OpenApiParameter(
                "zone",
                OpenApiTypes.STR,
                description="Zone liturgique (défaut: afrique)",
            ),
        ],
        responses={200: OfficeSerializer},
        tags=["Liturgy"],
        summary="Office de la Liturgie des Heures (clergé uniquement)",
    )
    def get(self, request):
        if not self.office_type:
            return Response(
                {"detail": "Office type not configured."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        date_str, zone = self._get_params(request)
        date_obj, valid = self._ensure_data(date_str, zone)

        if not valid:
            return Response(
                {"detail": "Format de date invalide. Utilisez YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not date_obj:
            return Response(
                {"detail": "Données liturgiques non disponibles."},
                status=status.HTTP_404_NOT_FOUND,
            )
        office = date_obj.offices.filter(office_type=self.office_type).first()
        if not office:
            return Response(
                {"detail": f"Office '{self.office_type}' non trouvé pour cette date."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(OfficeSerializer(office).data)


# ---------------------------------------------------------------------------
# Public endpoints — informations + messes
# ---------------------------------------------------------------------------


class LiturgyTodayApi(ApiAuthMixin, APIView):
    """Jour liturgique V1, public (EF-PAR-01, -02, -05)."""

    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: OpenApiTypes.OBJECT},
        tags=["Liturgy"],
        summary="Aujourd'hui : calendrier (calcul local), lectures selon LITURGY_SOURCE, méditation",
    )
    def get(self, request):
        return Response(selectors.liturgy_day(day=timezone.localdate(), user=request.user))


class LiturgyDateApi(ApiAuthMixin, APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: OpenApiTypes.OBJECT},
        tags=["Liturgy"],
        summary="Jour liturgique d'une date (YYYY-MM-DD)",
    )
    def get(self, request, day):
        return Response(selectors.liturgy_day(day=day, user=request.user))


class OfficeDetailApi(ApiAuthMixin, APIView):
    # Un office isolé = Liturgie des Heures → réservé au clergé/religieux, comme
    # les endpoints /v1/<office>/. Évite le contournement du gate par pk direct.
    permission_classes = [CanAccessLiturgyOfHours]

    @extend_schema(
        responses={200: OfficeSerializer},
        tags=["Liturgy"],
        summary="Détail d'un office liturgique (clergé uniquement)",
    )
    @method_decorator(cache_page(60 * 60 * 24))
    def get(self, request, pk):
        try:
            office = Office.objects.get(pk=pk)
        except Office.DoesNotExist:
            return Response({"detail": "Office introuvable."}, status=status.HTTP_404_NOT_FOUND)
        return Response(OfficeSerializer(office).data)


# ---------------------------------------------------------------------------
# Liturgy of the Hours — clergy-only (7 offices)
# ---------------------------------------------------------------------------


class LiturgyLaudesApi(_OfficeBase):
    office_type = "laudes"


class LiturgyTierceApi(_OfficeBase):
    office_type = "tierce"


class LiturgySexteApi(_OfficeBase):
    office_type = "sexte"


class LiturgyNoneApi(_OfficeBase):
    office_type = "none"


class LiturgyVepresApi(_OfficeBase):
    office_type = "vepres"


class LiturgyCompliesApi(_OfficeBase):
    office_type = "complies"


class LiturgyLecturesApi(_OfficeBase):
    office_type = "lectures"
