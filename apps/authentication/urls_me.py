from django.urls import path

from apps.authentication.apis_ws import WsTicketApi

urlpatterns = [
    path("ws-ticket/", WsTicketApi.as_view(), name="ws-ticket"),
]
