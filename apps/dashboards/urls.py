from django.urls import path

from apps.dashboards import apis

urlpatterns = [
    path("nodes/<uuid:node_id>/", apis.NodeDashboardApi.as_view(), name="node"),
    path("platform/", apis.PlatformDashboardApi.as_view(), name="platform"),
]
