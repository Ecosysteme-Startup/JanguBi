from django.urls import path

from apps.core.modules import is_module_active
from apps.liturgy.apis import (
    LiturgyCompliesApi,
    LiturgyDateApi,
    LiturgyInformationsApi,
    LiturgyLaudesApi,
    LiturgyLecturesApi,
    LiturgyMessesApi,
    LiturgyNoneApi,
    LiturgySexteApi,
    LiturgyTierceApi,
    LiturgyTodayApi,
    LiturgyVepresApi,
    OfficeDetailApi,
    ReadingDetailApi,
)

urlpatterns = [
    # V1 Flexible Endpoints (Query params based)
    path("v1/informations/", LiturgyInformationsApi.as_view(), name="v1-informations"),
    path("v1/messes/", LiturgyMessesApi.as_view(), name="v1-messes"),
    path("v1/lectures/", LiturgyLecturesApi.as_view(), name="v1-lectures"),

    # Legacy / Compatibility Dates
    path("today/", LiturgyTodayApi.as_view(), name="today"),
    path("date/<str:date_str>/", LiturgyDateApi.as_view(), name="specific-date"),
    
    # Specific Resource Breakdown
    path("readings/<int:pk>/", ReadingDetailApi.as_view(), name="reading-detail"),
]

# Liturgie des Heures — gelée en V1 faute d'accord AELF (ADR-006/008, « liturgy.heures »).
if is_module_active("liturgy.heures"):
    urlpatterns += [
        path("v1/laudes/", LiturgyLaudesApi.as_view(), name="v1-laudes"),
        path("v1/tierce/", LiturgyTierceApi.as_view(), name="v1-tierce"),
        path("v1/sexte/", LiturgySexteApi.as_view(), name="v1-sexte"),
        path("v1/none/", LiturgyNoneApi.as_view(), name="v1-none"),
        path("v1/vepres/", LiturgyVepresApi.as_view(), name="v1-vepres"),
        path("v1/complies/", LiturgyCompliesApi.as_view(), name="v1-complies"),
        path("offices/<int:pk>/", OfficeDetailApi.as_view(), name="office-detail"),
    ]
