import datetime

from django.urls import path, register_converter

from apps.core.modules import is_module_active
from apps.liturgy.apis import (
    LiturgyCompliesApi,
    LiturgyDateApi,
    LiturgyLaudesApi,
    LiturgyLecturesApi,
    LiturgyNoneApi,
    LiturgySexteApi,
    LiturgyTierceApi,
    LiturgyTodayApi,
    LiturgyVepresApi,
    OfficeDetailApi,
)


class IsoDateConverter:
    regex = r"\d{4}-\d{2}-\d{2}"

    def to_python(self, value: str) -> datetime.date:
        try:
            return datetime.date.fromisoformat(value)
        except ValueError as exc:  # 2026-02-30 : 404 plutôt que 500
            raise ValueError(value) from exc

    def to_url(self, value: datetime.date) -> str:
        return value.isoformat()


register_converter(IsoDateConverter, "isodate")

# V1 (ADR-008, ADR-013) : le jour liturgique, calendrier calculé localement. Les anciennes
# routes de relais AELF (v1/informations, v1/messes, date/<str>, readings/<pk>) sont retirées.
urlpatterns = [
    path("today/", LiturgyTodayApi.as_view(), name="today"),
    path("<isodate:day>/", LiturgyDateApi.as_view(), name="day"),
]

# Liturgie des Heures (dont l'office des lectures) — gelée en V1 faute d'accord AELF.
if is_module_active("liturgy.heures"):
    urlpatterns += [
        path("v1/laudes/", LiturgyLaudesApi.as_view(), name="v1-laudes"),
        path("v1/tierce/", LiturgyTierceApi.as_view(), name="v1-tierce"),
        path("v1/sexte/", LiturgySexteApi.as_view(), name="v1-sexte"),
        path("v1/none/", LiturgyNoneApi.as_view(), name="v1-none"),
        path("v1/vepres/", LiturgyVepresApi.as_view(), name="v1-vepres"),
        path("v1/complies/", LiturgyCompliesApi.as_view(), name="v1-complies"),
        path("v1/lectures/", LiturgyLecturesApi.as_view(), name="v1-lectures"),
        path("offices/<int:pk>/", OfficeDetailApi.as_view(), name="office-detail"),
    ]
