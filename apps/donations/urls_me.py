from django.urls import path

from apps.donations import apis

urlpatterns = [
    path("", apis.MyDonationsApi.as_view(), name="list"),
    path("resume/", apis.MySummaryApi.as_view(), name="summary"),
    path("<uuid:donation_id>/recu/", apis.MyReceiptApi.as_view(), name="receipt"),
]
