from django.urls import path

from apps.messaging.apis_preferences import NotificationPreferenceApi
from apps.messaging.apis_presence import PresenceSettingApi

urlpatterns = [
    path("notification-preferences/", NotificationPreferenceApi.as_view(), name="notification-preferences"),
    path("presence/", PresenceSettingApi.as_view(), name="presence"),
]
