from django.urls import path

from apps.documents import apis

urlpatterns = [
    path("", apis.QueueApi.as_view(), name="queue"),
    path("counts/", apis.QueueCountsApi.as_view(), name="counts"),
    path("stats/", apis.SupervisionStatsApi.as_view(), name="stats"),
    path("<uuid:request_id>/", apis.ProcessorDetailApi.as_view(), name="detail"),
    path("<uuid:request_id>/register-ref/", apis.RegisterRefApi.as_view(), name="register-ref"),
    path("<uuid:request_id>/notes/", apis.NotesApi.as_view(), name="notes"),
    path("<uuid:request_id>/logs/", apis.LogsApi.as_view(), name="logs"),
    path("<uuid:request_id>/<slug:transition>/", apis.ProcessorTransitionApi.as_view(), name="transition"),
]
