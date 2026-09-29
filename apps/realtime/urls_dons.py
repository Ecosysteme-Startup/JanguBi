from django.db import transaction
from django.urls import path

from apps.realtime.apis import DonsFluxApi

urlpatterns = [
    # Hors ATOMIC_REQUESTS : un flux dure jusqu'à 30 min et ne doit tenir ni transaction ni connexion.
    path("", transaction.non_atomic_requests(DonsFluxApi.as_view()), name="flux"),
]
