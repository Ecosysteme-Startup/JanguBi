from django.urls import path

from apps.hierarchy import apis_offices

urlpatterns = [
    path("", apis_offices.AuditListApi.as_view(), name="list"),
]
