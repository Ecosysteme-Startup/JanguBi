from django.urls import path

from apps.hierarchy import apis_memberships, apis_offices

urlpatterns = [
    path("capacites/", apis_offices.MeCapacitesApi.as_view(), name="capacites"),
    path("declaration/", apis_offices.MeDeclarationApi.as_view(), name="declaration"),
    path("paroisse-suivie/", apis_offices.MeParoisseSuivieApi.as_view(), name="paroisse-suivie"),
    # Paroisses multiples (décisions 6-8)
    path("paroisses/", apis_memberships.MesParoissesApi.as_view(), name="paroisses"),
    path("paroisses/<uuid:node_id>/", apis_memberships.MaParoisseApi.as_view(), name="paroisse"),
    path(
        "paroisses/<uuid:node_id>/principale/",
        apis_memberships.MaParoissePrincipaleApi.as_view(),
        name="paroisse-principale",
    ),
]
