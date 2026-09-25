from django.urls import path

from apps.confessions import apis

urlpatterns = [
    path("slots/", apis.SlotListApi.as_view(), name="slots"),
    path("bookings/", apis.BookingCreateApi.as_view(), name="booking-create"),
    path("bookings/<int:booking_id>/cancel/", apis.BookingCancelApi.as_view(), name="booking-cancel"),
]
