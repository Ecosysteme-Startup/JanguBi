from django.urls import path

from apps.search import apis

urlpatterns = [
    path("", apis.SearchApi.as_view(), name="search"),
]
