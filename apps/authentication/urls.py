from django.conf import settings
from django.urls import path

from .apis import (
    UserJwtLoginApi,
    UserJwtLogoutAllApi,
    UserJwtLogoutApi,
    UserJwtRefreshApi,
    UserMeApi,
)

# --- JWT historique (SimpleJWT) : retiré du chemin actif après la bascule Keycloak
# (LEGACY_JWT_ENABLED=false) ; le code part en L9 (ADR-004).
_legacy_jwt = [
    path("jwt/login/", UserJwtLoginApi.as_view(), name="jwt-login"),
    path("jwt/refresh/", UserJwtRefreshApi.as_view(), name="jwt-refresh"),
    path("jwt/logout/", UserJwtLogoutApi.as_view(), name="jwt-logout"),
    path("jwt/logout-all/", UserJwtLogoutAllApi.as_view(), name="jwt-logout-all"),
]

urlpatterns = [
    *(_legacy_jwt if settings.LEGACY_JWT_ENABLED else []),

    # --- Session (Django Admin + fallback Safari) ---
    # path("session/login/", UserSessionLoginApi.as_view(), name="session-login"),
    # path("session/logout/", UserSessionLogoutApi.as_view(), name="session-logout"),

    # --- Profil connecté ---
    path("me/", UserMeApi.as_view(), name="me"),
]
