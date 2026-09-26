from django.urls import path

from apps.hierarchy import apis, apis_offices

urlpatterns = [
    path("node-types/", apis.NodeTypeListApi.as_view(), name="node-type-list"),
    path("nodes/", apis.NodeListCreateApi.as_view(), name="node-list"),
    path("nodes/<uuid:node_id>/", apis.NodeDetailApi.as_view(), name="node-detail"),
    path("nodes/<uuid:node_id>/children/", apis.NodeChildrenApi.as_view(), name="node-children"),
    path("nodes/<uuid:node_id>/ancestors/", apis.NodeAncestorsApi.as_view(), name="node-ancestors"),
    path("nodes/<uuid:node_id>/places/", apis.NodePlaceListCreateApi.as_view(), name="node-places"),
    path("places/<int:place_id>/", apis.PlaceDetailApi.as_view(), name="place-detail"),
    path("places/<int:place_id>/schedule/", apis.PlaceScheduleApi.as_view(), name="place-schedule"),
    path("places/<int:place_id>/exceptions/", apis.PlaceExceptionListCreateApi.as_view(), name="place-exceptions"),
    path(
        "places/<int:place_id>/exceptions/<int:exception_id>/",
        apis.PlaceExceptionDeleteApi.as_view(),
        name="place-exception-delete",
    ),
    path("import/nodes/", apis.NodeImportApi.as_view(), name="import-nodes"),
    path("import/places/", apis.PlaceImportApi.as_view(), name="import-places"),
    # Offices et nominations (L2)
    path("office-types/", apis_offices.OfficeTypeListApi.as_view(), name="office-type-list"),
    path("persons/", apis_offices.PersonSearchApi.as_view(), name="person-search"),
    path("assignments/", apis_offices.AssignmentListCreateApi.as_view(), name="assignment-list"),
    path("assignments/import/", apis_offices.AssignmentImportApi.as_view(), name="assignment-import"),
    path("assignments/<int:assignment_id>/", apis_offices.AssignmentDetailApi.as_view(), name="assignment-detail"),
    path("verifications/", apis_offices.VerificationListApi.as_view(), name="verification-list"),
    path(
        "verifications/<uuid:person_id>/decision/",
        apis_offices.VerificationDecisionApi.as_view(),
        name="verification-decision",
    ),
    path("capability-overrides/", apis_offices.CapabilityOverrideListCreateApi.as_view(), name="override-list"),
    path(
        "capability-overrides/<int:override_id>/",
        apis_offices.CapabilityOverrideDeleteApi.as_view(),
        name="override-delete",
    ),
]
