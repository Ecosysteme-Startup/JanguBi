from django.urls import path

from apps.donations import apis

urlpatterns = [
    path("paroisses/<uuid:node_id>/", apis.PublicParishApi.as_view(), name="parish"),
    path("fonds/<uuid:fund_id>/", apis.PublicFundApi.as_view(), name="fund"),
]
