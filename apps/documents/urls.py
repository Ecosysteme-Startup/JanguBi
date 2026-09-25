from django.urls import path

from apps.documents import apis

urlpatterns = [
    path("requests/", apis.RequestListCreateApi.as_view(), name="request-list"),
    path("requests/options/", apis.RequestOptionsApi.as_view(), name="request-options"),
    path("requests/<uuid:request_id>/", apis.RequestDetailApi.as_view(), name="request-detail"),
    path("requests/<uuid:request_id>/supplement/", apis.RequestSupplementApi.as_view(), name="request-supplement"),
    path("requests/<uuid:request_id>/cancel/", apis.RequestCancelApi.as_view(), name="request-cancel"),
]
