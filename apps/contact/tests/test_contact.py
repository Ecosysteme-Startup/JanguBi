"""Formulaire public « Pour les paroisses » : POST /api/v1/public/contact/."""

import logging

import pytest
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from apps.contact.models import PresentationRequest
from apps.emails.models import Email

pytestmark = pytest.mark.django_db
URL = "/api/v1/public/contact/"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()


def payload(**overrides):
    data = {
        "full_name": "Abbé Jean Diouf",
        "fonction": "cure",
        "paroisse": "Saint-Dominique",
        "diocese_node_id": None,
        "telephone": "+221 77 123 45 67",
        "email": "cure@saint-dominique.sn",
        "message": "Nous aimerions une présentation.",
        "consentement": True,
        "cure_informe": True,
    }
    data.update(overrides)
    return data


def test_create_records_request_and_notifies_numerisen(tree, django_capture_on_commit_callbacks):
    client = APIClient()

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(URL, payload(diocese_node_id=str(tree.dakar.pk)), format="json")

    assert response.status_code == 201
    assert response.json() == {"received": True}
    request = PresentationRequest.objects.get()
    assert request.diocese_node == tree.dakar
    assert request.fonction == "cure" and request.cure_informe is True
    assert request.consented_at is not None
    email = Email.objects.get()
    assert email.to == settings.CONTACT_EMAIL
    assert "Saint-Dominique" in email.subject
    assert "Archidiocèse de Dakar" in email.plain_text
    assert len(mail.outbox) == 1 and mail.outbox[0].to == [settings.CONTACT_EMAIL]


def test_message_is_optional_and_html_is_escaped(db):
    response = APIClient().post(URL, payload(message=None) | {"full_name": "<script>x</script>"}, format="json")
    assert response.status_code == 400  # message null refusé

    data = payload(full_name="<b>Awa</b>")
    del data["message"]
    response = APIClient().post(URL, data, format="json")
    assert response.status_code == 201
    email = Email.objects.get()
    assert "<b>Awa</b>" not in email.html
    assert "&lt;b&gt;Awa&lt;/b&gt;" in email.html


def test_consent_is_mandatory(db):
    response = APIClient().post(URL, payload(consentement=False), format="json")
    assert response.status_code == 400
    assert list(response.json()) == ["consentement"]
    assert not PresentationRequest.objects.exists() and not Email.objects.exists()


def test_errors_are_reported_per_field(db):
    response = APIClient().post(
        URL,
        {"fonction": "sacristain", "email": "pas-un-email", "telephone": "abc", "message": "x" * 1001},
        format="json",
    )
    assert response.status_code == 400
    body = response.json()
    for field in ("full_name", "fonction", "paroisse", "telephone", "email", "message", "consentement", "cure_informe"):
        assert isinstance(body[field], list) and body[field], field


def test_single_line_fields_reject_newlines(db):
    response = APIClient().post(URL, payload(paroisse="Saint-Dominique\nBcc: x@y.z"), format="json")
    assert response.status_code == 400
    assert "paroisse" in response.json()


def test_diocese_must_be_an_existing_diocese(tree):
    client = APIClient()
    not_a_diocese = client.post(URL, payload(diocese_node_id=str(tree.saint_dominique.pk)), format="json")
    unknown = client.post(URL, payload(diocese_node_id="00000000-0000-0000-0000-000000000000"), format="json")

    for response in (not_a_diocese, unknown):
        assert response.status_code == 400
        assert list(response.json()) == ["diocese_node_id"]
    assert not PresentationRequest.objects.exists()


def test_public_endpoint_ignores_authorization_header(db):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer jeton-invalide")
    assert client.post(URL, payload(), format="json").status_code == 201


@override_settings(CONTACT_THROTTLE_RATE="2/hour")
def test_anonymous_throttle(db):
    client = APIClient()
    assert client.post(URL, payload(), format="json").status_code == 201
    assert client.post(URL, payload(), format="json").status_code == 201
    assert client.post(URL, payload(), format="json").status_code == 429
    assert PresentationRequest.objects.count() == 2


def test_no_personal_data_in_logs(db, caplog, django_capture_on_commit_callbacks):
    caplog.set_level(logging.DEBUG)
    with django_capture_on_commit_callbacks(execute=True):
        APIClient().post(URL, payload(telephone="+221 70 999 88 77", email="secret-cure@test.sn"), format="json")
    assert "secret-cure@test.sn" not in caplog.text
    assert "70 999 88 77" not in caplog.text
