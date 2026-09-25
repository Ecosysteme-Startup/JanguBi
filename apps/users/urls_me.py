from django.urls import path

from apps.users.apis_privacy import MeApi, MeConsentApi, MeExportApi

# Personne connectée sous /api/v1/me/ (SRS §7). /users/me/ reste un alias du profil.
urlpatterns = [
    path("", MeApi.as_view(), name="detail"),
    path("consent/", MeConsentApi.as_view(), name="consent"),
    path("export/", MeExportApi.as_view(), name="export"),
]
