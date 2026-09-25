"""Gel des modules hors V1 (ADR-006, plan L0.4)."""

import importlib
from typing import Any

import pytest
from celery.schedules import crontab
from django.test import override_settings
from django.urls import Resolver404, clear_url_caches, include, path, resolve

from apps.core.modules import (
    FROZEN_BY_DEFAULT,
    V1_DEFAULT_MODULES,
    filter_beat_schedule,
    is_module_active,
    task_module,
)

FROZEN_ROUTES = [
    "/api/v1/donations/",
    "/api/v1/mass-intentions/",
    "/api/v1/transfers/",
    "/api/v1/spiritual/",
    "/api/v1/tv/",
    "/api/v1/rag/",
    "/api/v1/clergy-accounts/",
]


class _V1UrlConf:
    """Urlconf construit avec les modules par défaut de la V1."""

    def __init__(self) -> None:
        from apps.api.urls import build_v1_patterns

        self.urlpatterns = [
            path("api/", include(([path("v1/", include(build_v1_patterns(active=V1_DEFAULT_MODULES)))], "api")))
        ]


def _resolves(url: str, urlconf: Any) -> bool:
    try:
        resolve(url, urlconf=urlconf)
    except Resolver404:
        return False
    return True


# --- is_module_active ---------------------------------------------------------


def test_core_modules_are_always_active():
    assert is_module_active("users", active=[])
    assert is_module_active("authentication", active=[])


def test_submodule_requires_its_parent():
    assert not is_module_active("liturgy.heures", active=["liturgy.heures"])
    assert is_module_active("liturgy.heures", active=["liturgy", "liturgy.heures"])


def test_v1_default_excludes_every_frozen_module():
    assert not FROZEN_BY_DEFAULT & set(V1_DEFAULT_MODULES)
    for module in ("bible", "liturgy", "rosary", "messaging", "documents", "news", "agenda", "dashboards", "confessions"):
        assert module in V1_DEFAULT_MODULES


# --- routes ------------------------------------------------------------------


@pytest.mark.parametrize("url", FROZEN_ROUTES)
def test_frozen_route_returns_404_with_v1_defaults(url):
    assert not _resolves(url, _V1UrlConf())


@pytest.mark.parametrize(
    "prefix", ["me/", "bible/", "liturgy/", "rosary/", "messaging/", "documents/", "news/", "agenda/", "hierarchy/"]
)
def test_v1_routes_stay_exposed(prefix):
    from apps.api.urls import build_v1_patterns

    assert prefix in {str(p.pattern) for p in build_v1_patterns(active=V1_DEFAULT_MODULES)}


@pytest.mark.django_db
def test_frozen_route_is_404_over_http(client, settings):
    settings.ROOT_URLCONF = _V1UrlConf()
    clear_url_caches()
    try:
        response = client.get("/api/v1/donations/")
    finally:
        clear_url_caches()
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("module", "submodule", "url", "kept_url"),
    [
        ("apps.liturgy.urls", "liturgy.heures", "/v1/lectures/", "/today/"),
        ("apps.bible.urls", "bible.avance", "/lectio/", "/books/"),
        ("apps.rosary.urls", "rosary.communautaire", "/community/", "/today/"),
    ],
)
def test_frozen_submodule_routes_are_removed(module, submodule, url, kept_url):
    active = [m for m in V1_DEFAULT_MODULES]
    urls_module = importlib.import_module(module)
    try:
        with override_settings(JANGUBI_MODULES=active):
            importlib.reload(urls_module)
            patterns = {"/" + str(p.pattern) for p in urls_module.urlpatterns}
        assert url not in patterns
        assert kept_url in patterns
    finally:
        importlib.reload(urls_module)
        clear_url_caches()


# --- Beat --------------------------------------------------------------------


def test_task_module_is_derived_from_task_path():
    assert task_module("apps.donations.tasks.remind") == "donations"
    assert task_module("celery.backend_cleanup") is None


def test_frozen_task_is_absent_from_beat_schedule():
    schedule = {
        "lectio_reminder": {"task": "apps.bible.tasks.remind", "schedule": crontab(hour=1), "module": "bible.avance"},
        "purge_conversations": {"task": "apps.messaging.tasks.purge", "schedule": crontab(hour=3)},
        "hours_sync": {"task": "apps.liturgy.tasks.sync_hours", "schedule": crontab(hour=2), "module": "liturgy.heures"},
        "celery_cleanup": {"task": "celery.backend_cleanup", "schedule": crontab(hour=4)},
    }

    kept = filter_beat_schedule(schedule, active=V1_DEFAULT_MODULES)

    assert set(kept) == {"purge_conversations", "celery_cleanup"}
    assert "module" not in kept["purge_conversations"]


def test_settings_beat_schedule_contains_no_frozen_task(settings):
    for entry in settings.CELERY_BEAT_SCHEDULE.values():
        module = task_module(entry["task"])
        assert module not in FROZEN_BY_DEFAULT
