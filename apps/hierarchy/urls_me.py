from django.urls import path

from apps.hierarchy import apis_offices

urlpatterns = [
    path("capacites/", apis_offices.MeCapacitesApi.as_view(), name="capacites"),
    path("declaration/", apis_offices.MeDeclarationApi.as_view(), name="declaration"),
    path("paroisse-suivie/", apis_offices.MeParoisseSuivieApi.as_view(), name="paroisse-suivie"),
]
