from django.urls import path

from apps.users.apis_keycloak_webhook import KeycloakWebhookApi

urlpatterns = [
    path("events/", KeycloakWebhookApi.as_view(), name="events"),
]
