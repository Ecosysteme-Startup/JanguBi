from django.urls import path

from apps.contact import apis

urlpatterns = [
    path("", apis.PublicContactApi.as_view(), name="create"),
]
