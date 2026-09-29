from django.urls import path

from apps.confessions import apis

urlpatterns = [
    path("rules/", apis.RuleListCreateApi.as_view(), name="rules"),
    path("rules/<int:rule_id>/", apis.RuleDetailApi.as_view(), name="rule-detail"),
    path("sessions/", apis.SessionOpenApi.as_view(), name="sessions"),
    path("planning/", apis.PlanningApi.as_view(), name="planning"),
    path("slots/<int:slot_id>/cancel/", apis.SlotCancelApi.as_view(), name="slot-cancel"),
    path("bookings/<int:booking_id>/attendance/", apis.AttendanceApi.as_view(), name="attendance"),
]
