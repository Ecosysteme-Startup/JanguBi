from django.urls import path

from apps.messaging.apis_preferences import NotificationPreferenceApi

urlpatterns = [
    path("notification-preferences/", NotificationPreferenceApi.as_view(), name="notification-preferences"),
]
