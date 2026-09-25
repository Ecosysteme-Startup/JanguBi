from django.urls import path

from apps.confessions import apis

urlpatterns = [
    path("", apis.MyBookingsApi.as_view(), name="list"),
]
