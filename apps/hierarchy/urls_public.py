from django.urls import path

from apps.hierarchy import apis

urlpatterns = [
    path("nodes/", apis.PublicDirectoryApi.as_view(), name="directory"),
    path("nodes/<uuid:node_id>/week/", apis.PublicNodeWeekApi.as_view(), name="node-week"),
]
