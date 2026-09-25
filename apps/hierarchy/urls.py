from django.urls import path

from apps.hierarchy import apis

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
]
