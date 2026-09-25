from django.urls import path

from apps.agenda import apis

urlpatterns = [
    path("", apis.StaffEventListCreateApi.as_view(), name="list"),
    path("<int:event_id>/", apis.StaffEventDetailApi.as_view(), name="detail"),
    path("<int:event_id>/registrations/", apis.StaffEventRegistrationsApi.as_view(), name="registrations"),
    path("<int:event_id>/registrations.csv", apis.StaffEventRegistrationsCsvApi.as_view(), name="registrations-csv"),
]
