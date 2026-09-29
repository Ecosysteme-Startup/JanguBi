from django.urls import path

from apps.agenda import apis

urlpatterns = [
    path("", apis.EventListApi.as_view(), name="list"),
    path("<int:event_id>/", apis.EventDetailApi.as_view(), name="detail"),
    path("<int:event_id>/register/", apis.EventRegisterApi.as_view(), name="register"),
]
