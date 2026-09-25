from django.urls import path

from apps.news import apis

urlpatterns = [
    path("feed/", apis.MeFeedApi.as_view(), name="feed"),
]
