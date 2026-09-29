"""Exploitation (lot B2) : /metrics protégé et files Celery séparées."""

import pytest
from django.test import Client

from apps.tasks.celery import app as celery_app


@pytest.fixture
def metrics_settings(settings):
    settings.METRICS_ENABLED = True
    settings.METRICS_ALLOWED_CIDRS = ["10.0.0.0/8"]
    settings.METRICS_TOKEN = "s3cret-metrics"
    return settings


def test_metrics_open_to_allowlisted_collector(metrics_settings):
    response = Client(REMOTE_ADDR="10.1.2.3").get("/metrics")

    assert response.status_code == 200
    assert b"django_http_requests" in response.content


def test_metrics_hidden_from_other_addresses(metrics_settings):
    assert Client(REMOTE_ADDR="196.1.2.3").get("/metrics").status_code == 404


def test_metrics_through_public_proxy_needs_the_token(metrics_settings):
    # Adresse du proxy dans la liste, mais la requête vient d'Internet (X-Forwarded-For).
    proxied = Client(REMOTE_ADDR="10.1.2.3", HTTP_X_FORWARDED_FOR="10.1.2.3")
    assert proxied.get("/metrics").status_code == 404
    assert proxied.get("/metrics", HTTP_AUTHORIZATION="Bearer s3cret-metrics").status_code == 200
    assert proxied.get("/metrics", HTTP_AUTHORIZATION="Bearer mauvais").status_code == 404


def test_metrics_can_be_switched_off(metrics_settings):
    metrics_settings.METRICS_ENABLED = False

    assert Client(REMOTE_ADDR="10.1.2.3").get("/metrics").status_code == 404


@pytest.mark.parametrize(
    ("task", "queue"),
    [
        ("apps.emails.tasks.email_send", "default"),
        ("apps.messaging.tasks.push_deliver", "default"),
        ("apps.audio.tasks.audio_transcode_task", "media"),
        ("apps.audio.tasks_media.hls_package", "media"),
        ("apps.bible.tasks.bible_reco_recompute_task", "reco"),
        ("apps.audio.tasks.audio_reco_recompute_task", "reco"),
    ],
)
def test_celery_routes_tasks_to_separate_queues(task, queue):
    assert celery_app.amqp.router.route({}, task)["queue"].name == queue


def test_celery_declares_the_three_queues(settings):
    assert {q.name for q in settings.CELERY_TASK_QUEUES} == {"default", "media", "reco"}
    assert settings.CELERY_TASK_DEFAULT_QUEUE == "default"
