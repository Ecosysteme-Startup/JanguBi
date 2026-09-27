from django.urls import path

from apps.donations import apis

urlpatterns = [
    path("sante/", apis.HealthApi.as_view(), name="health"),
    path("activations/", apis.ActivationApi.as_view(), name="activations"),
]
