from django.urls import path

from apps.users.apis import UserMeDetailApi

# Profil de la personne connectée sous /api/v1/me/ (SRS §7). /users/me/ reste un alias.
urlpatterns = [
    path("", UserMeDetailApi.as_view(), name="detail"),
]
