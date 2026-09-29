"""apps URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.core.metrics import metrics_view
from apps.core.sante import sante_view

router = DefaultRouter()

urlpatterns = [
    path("", include(router.urls)),
    path("api-auth/", include("rest_framework.urls")),
    # Santé (test de fumée de l'Infrastructure) : avant l'include de /api/.
    path("api/sante/", sante_view, name="sante"),
    path("api/health/", sante_view, name="health"),
    path("api/", include(("apps.api.urls", "api"))),
    # Prometheus (django-prometheus) : réservé au collecteur (liste d'adresses ou jeton).
    path("metrics", metrics_view, name="prometheus-metrics"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# L'admin Django se connecte par mot de passe seul, sans MFA : désactivée par défaut en
# production (DJANGO_ADMIN_ENABLED), et à restreindre au réseau d'administration sinon.
if settings.DJANGO_ADMIN_ENABLED:
    urlpatterns.append(path(settings.DJANGO_ADMIN_URL, admin.site.urls))

from config.settings.debug_toolbar.setup import DebugToolbarSetup  # noqa

urlpatterns = DebugToolbarSetup.do_urls(urlpatterns)
