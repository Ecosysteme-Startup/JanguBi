from django.urls import path

from apps.dashboards import apis_taches

urlpatterns = [
    path("", apis_taches.TodayTasksApi.as_view(), name="today"),
]
