from collections.abc import Iterable

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from apps.core.modules import is_module_active

# (module, préfixe d'URL, urlconf, namespace). Les modules gelés (ADR-006,
# réglage JANGUBI_MODULES) ne sont pas inclus : leurs routes renvoient 404.
API_V1_ROUTES: tuple[tuple[str, str, str, str], ...] = (
    ("authentication", "auth/", "apps.authentication.urls", "authentication"),
    ("users", "users/", "apps.users.urls", "users"),
    ("errors", "errors/", "apps.errors.urls", "errors"),
    ("files", "files/", "apps.files.urls", "files"),
    ("bible", "bible/", "apps.bible.urls", "bible"),
    ("rosary", "rosary/", "apps.rosary.urls", "rosary"),
    ("tv", "tv/", "apps.tv.urls", "tv"),
    ("rag", "rag/", "apps.rag.urls", "rag"),
    ("liturgy", "liturgy/", "apps.liturgy.urls", "liturgy"),
    ("messaging", "messaging/", "apps.messaging.urls", "messaging"),
    # Notifications top-level (web + mobile RN) — les routes historiques
    # /messaging/notifications/ restent pour compatibilité.
    ("notifications", "notifications/", "apps.messaging.urls_notifications", "notifications"),
    ("documents", "documents/", "apps.documents.urls", "documents"),
    ("news", "news/", "apps.news.urls", "news"),
    ("org", "org/", "apps.org.urls", "org"),
    ("hierarchy", "hierarchy/", "apps.hierarchy.urls", "hierarchy"),
    ("hierarchy", "public/", "apps.hierarchy.urls_public", "public"),
    ("clergy_accounts", "clergy-accounts/", "apps.clergy_accounts.urls", "clergy-accounts"),
    ("agenda", "agenda/", "apps.agenda.urls", "agenda"),
    ("mass_intentions", "mass-intentions/", "apps.mass_intentions.urls", "mass-intentions"),
    ("donations", "donations/", "apps.donations.urls", "donations"),
    ("dashboards", "dashboards/", "apps.dashboards.urls", "dashboards"),
    ("spiritual", "spiritual/", "apps.spiritual.urls", "spiritual"),
    ("transfers", "transfers/", "apps.transfers.urls", "transfers"),
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
