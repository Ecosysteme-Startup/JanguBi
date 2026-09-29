from collections.abc import Iterable

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from apps.core.modules import is_module_active

# (module, préfixe d'URL, urlconf, namespace). Les modules gelés (ADR-006,
# réglage JANGUBI_MODULES) ne sont pas inclus : leurs routes renvoient 404.
API_V1_ROUTES: tuple[tuple[str, str, str, str], ...] = (
    ("files", "files/", "apps.files.urls", "files"),
    ("bible", "bible/", "apps.bible.urls", "bible"),
    ("rosary", "rosary/", "apps.rosary.urls", "rosary"),
    ("liturgy", "liturgy/", "apps.liturgy.urls", "liturgy"),
    ("messaging", "messaging/", "apps.messaging.urls", "messaging"),
    # Notifications top-level (web + mobile RN) — les routes historiques
    # /messaging/notifications/ restent pour compatibilité.
    ("notifications", "notifications/", "apps.messaging.urls_notifications", "notifications"),
    ("documents", "documents/", "apps.documents.urls", "documents"),
    ("documents", "staff/documents/", "apps.documents.urls_staff", "staff-documents"),
    ("news", "news/", "apps.news.urls", "news"),
    ("news", "staff/news/", "apps.news.urls_staff", "staff-news"),
    ("news", "me/", "apps.news.urls_me", "me-news"),
    ("notifications", "me/", "apps.messaging.urls_me", "me-notifications"),
    ("hierarchy", "hierarchy/", "apps.hierarchy.urls", "hierarchy"),
    ("contact", "public/contact/", "apps.contact.urls", "public-contact"),
    ("hierarchy", "public/", "apps.hierarchy.urls_public", "public"),
    ("users", "me/", "apps.users.urls_me", "me-profile"),
    ("users", "platform/accounts/", "apps.users.urls_platform", "platform-accounts"),
    # Administration des comptes synchronisée avec Keycloak (docs/ADMIN-KEYCLOAK.md).
    ("users", "admin/", "apps.users.urls_admin", "admin-accounts"),
    ("users", "integrations/keycloak/", "apps.users.urls_integrations", "keycloak-integration"),
    ("authentication", "me/", "apps.authentication.urls_me", "me-auth"),
    ("hierarchy", "me/", "apps.hierarchy.urls_me", "me"),
    ("hierarchy", "audit/", "apps.hierarchy.urls_audit", "audit"),
    ("confessions", "confessions/", "apps.confessions.urls", "confessions"),
    ("confessions", "staff/confessions/", "apps.confessions.urls_staff", "staff-confessions"),
    ("confessions", "me/confession-bookings/", "apps.confessions.urls_me", "me-confessions"),
    ("agenda", "agenda/", "apps.agenda.urls", "agenda"),
    ("agenda", "staff/agenda/", "apps.agenda.urls_staff", "staff-agenda"),
    ("dashboards", "dashboards/", "apps.dashboards.urls", "dashboards"),
    ("donations", "dons/", "apps.donations.urls", "dons"),
    ("donations", "public/dons/", "apps.donations.urls_public", "public-dons"),
    ("donations", "me/dons/", "apps.donations.urls_me", "me-dons"),
    ("donations", "staff/dons/", "apps.donations.urls_staff", "staff-dons"),
    # Flux SSE des tableaux de bord (lot B2, docs/TEMPS-REEL.md).
    ("donations", "staff/dons/flux/", "apps.realtime.urls_dons", "staff-dons-flux"),
    ("donations", "platform/dons/", "apps.donations.urls_platform", "platform-dons"),
    ("audio", "audio/", "apps.audio.urls", "audio"),
    # Lot V1-routes (docs/API-V1-COMPLEMENTS.md).
    ("invitations", "clergy-accounts/", "apps.invitations.urls", "clergy-accounts"),
    ("intentions", "mass-intentions/", "apps.intentions.urls", "mass-intentions"),
    ("search", "search/", "apps.search.urls", "search"),
    ("dashboards", "staff/taches-du-jour/", "apps.dashboards.urls_taches", "staff-taches"),
)


def build_v1_patterns(*, active: Iterable[str] | None = None) -> list:
    active_list = None if active is None else list(active)
    return [
        path(prefix, include((urlconf, namespace)))
        for module, prefix, urlconf, namespace in API_V1_ROUTES
        if is_module_active(module, active=active_list)
    ]


urlpatterns = [
    path("v1/", include(build_v1_patterns())),
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('swagger-ui/', SpectacularSwaggerView.as_view(url_name='api:schema'), name='swagger-ui'),
    path('redoc/', SpectacularRedocView.as_view(url_name='api:schema'), name='redoc'),
]
