"""Envoi push FCM HTTP v1 et APNs (lot B2), sans réseau : respx simule les deux fournisseurs."""

import datetime
import json
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from django.core.cache import cache
from django.utils import timezone

from apps.hierarchy.tests.factories import person, priest
from apps.messaging.models import NotificationPreference, PushDevice
from apps.messaging.push_providers import APNS_HOST, FCM_SEND_URL, ApnsProvider, FcmProvider, PushMessage
from apps.messaging.services import notification_send, push_device_register
from apps.messaging.services_notifications import people_notify
from apps.messaging.services_push import push_content, push_data, push_deliver_now
from apps.users.models import Profile

TOKEN_URI = "https://oauth2.googleapis.com/token"
FCM_URL = FCM_SEND_URL.format(project="jangubi-test")
IOS_TOKEN = "a" * 64
ANDROID_TOKEN = "fcm-android-token:APA91b-test"


def _pem(key) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def ec_key():
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def push_settings(settings, rsa_key, ec_key):
    cache.clear()
    settings.PUSH_ENABLED = True
    settings.FCM_PROJECT_ID = "jangubi-test"
    settings.FCM_SERVICE_ACCOUNT_JSON = json.dumps(
        {
            "type": "service_account",
            "project_id": "jangubi-test",
            "private_key_id": "k1",
            "private_key": _pem(rsa_key),
            "client_email": "push@jangubi-test.iam.gserviceaccount.com",
            "token_uri": TOKEN_URI,
        }
    )
    settings.APNS_TEAM_ID = "TEAM123456"
    settings.APNS_KEY_ID = "KEY1234567"
    settings.APNS_PRIVATE_KEY = _pem(ec_key)
    settings.APNS_TOPIC = "sn.numerisen.jangubi"
    settings.APNS_USE_SANDBOX = False
    yield settings
    cache.clear()


def _named(user, first: str, last: str):
    Profile.objects.update_or_create(user=user, defaults={"first_name": first, "last_name": last})
    user.refresh_from_db()
    return user


@pytest.fixture
def pere(db):
    return _named(priest("emmanuel.tine@sd.sn"), "Emmanuel", "Tine")


@pytest.fixture
def marie(db):
    return _named(person("marie.therese.diouf@test.sn"), "Marie-Thérèse", "Diouf")


def _mock_fcm_token(router):
    return router.post(TOKEN_URI).mock(
        return_value=httpx.Response(200, json={"access_token": "ya29.test", "expires_in": 3600})
    )


# --- Contenu : rien de sensible ------------------------------------------------------------------


def test_new_message_text_names_the_priest_without_excerpt(pere, marie):
    payload = {"conversation_id": "c-1", "sender_id": str(pere.pk), "sender_name": "Emmanuel Tine"}

    assert push_content(event_type="new_message", payload=payload) == (
        "Jàngu Bi",
        "Nouveau message du Père Emmanuel Tine",
    )
    assert push_content(event_type="new_message", payload={**payload, "sender_id": str(marie.pk)})[1] == (
        "Nouveau message de Marie-Thérèse Diouf"
    )


def test_sensitive_events_stay_generic():
    assert push_content(event_type="confessions.reminder", payload={"slot": "samedi 17 h"})[1] == (
        "Rappel : vous avez un rendez-vous prochainement."
    )
    assert push_content(event_type="inconnu", payload={})[1] == "Vous avez une nouvelle notification."


def test_data_carries_only_identifiers():
    data = push_data(
        event_type="new_message",
        payload={"conversation_id": "c-1", "sender_id": "u-1", "sender_name": "Emmanuel Tine", "sent_at": "x"},
        notification_id="n-1",
    )

    assert data == {"event_type": "new_message", "notification_id": "n-1", "conversation_id": "c-1"}


# --- FCM HTTP v1 -------------------------------------------------------------------------------------


@respx.mock(assert_all_mocked=True)
def test_fcm_sends_with_service_account_token(respx_mock, push_settings, marie):
    token_route = _mock_fcm_token(respx_mock)
    send_route = respx_mock.post(FCM_URL).mock(return_value=httpx.Response(200, json={"name": "projects/x/messages/1"}))
    device = PushDevice.objects.create(user=marie, platform="android", token=ANDROID_TOKEN)

    result = push_deliver_now(
        device_ids=[device.pk],
        title="Jàngu Bi",
        body="Nouveau message du Père Emmanuel Tine",
        data={"conversation_id": "c-1"},
    )

    assert result["sent"] == [device.pk]
    grant = parse_qs(token_route.calls.last.request.content.decode())
    assert grant["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
    assertion = jwt.decode(grant["assertion"][0], options={"verify_signature": False})
    assert assertion["scope"] == "https://www.googleapis.com/auth/firebase.messaging"
    request = send_route.calls.last.request
    assert request.headers["authorization"] == "Bearer ya29.test"
    body = json.loads(request.content)["message"]
    assert body["token"] == ANDROID_TOKEN
    assert body["notification"] == {"title": "Jàngu Bi", "body": "Nouveau message du Père Emmanuel Tine"}
    assert body["data"] == {"conversation_id": "c-1"}


@respx.mock
def test_fcm_unregistered_token_is_disabled(respx_mock, push_settings, marie):
    _mock_fcm_token(respx_mock)
    respx_mock.post(FCM_URL).mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {
                    "code": 404,
                    "status": "NOT_FOUND",
                    "details": [
                        {"@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError", "errorCode": "UNREGISTERED"}
                    ],
                }
            },
        )
    )
    device = PushDevice.objects.create(user=marie, platform="android", token=ANDROID_TOKEN)

    result = push_deliver_now(device_ids=[device.pk], title="t", body="b", data={})

    assert result["invalid"] == [device.pk]
    device.refresh_from_db()
    assert device.disabled_at is not None


@respx.mock
def test_fcm_server_error_is_retryable_and_keeps_token(respx_mock, push_settings, marie):
    _mock_fcm_token(respx_mock)
    respx_mock.post(FCM_URL).mock(return_value=httpx.Response(503, json={"error": {"status": "UNAVAILABLE"}}))
    device = PushDevice.objects.create(user=marie, platform="android", token=ANDROID_TOKEN)

    result = push_deliver_now(device_ids=[device.pk], title="t", body="b", data={})

    assert result["retry"] == [device.pk]
    device.refresh_from_db()
    assert device.disabled_at is None


# --- APNs ----------------------------------------------------------------------------------------------


@respx.mock
def test_apns_uses_jwt_provider_token(respx_mock, push_settings, ec_key, pere):
    route = respx_mock.post(f"{APNS_HOST}/3/device/{IOS_TOKEN}").mock(return_value=httpx.Response(200))
    device = PushDevice.objects.create(user=pere, platform="ios", token=IOS_TOKEN)

    result = push_deliver_now(
        device_ids=[device.pk],
        title="Jàngu Bi",
        body="Nouveau message de Marie-Thérèse Diouf",
        data={},
        collapse_id="n-1",
    )

    assert result["sent"] == [device.pk]
    request = route.calls.last.request
    assert request.headers["apns-topic"] == "sn.numerisen.jangubi"
    assert request.headers["apns-push-type"] == "alert"
    assert request.headers["apns-collapse-id"] == "n-1"
    provider_jwt = request.headers["authorization"].removeprefix("bearer ")
    assert jwt.get_unverified_header(provider_jwt)["kid"] == "KEY1234567"
    claims = jwt.decode(provider_jwt, ec_key.public_key(), algorithms=["ES256"])
    assert claims["iss"] == "TEAM123456"
    assert json.loads(request.content)["aps"]["alert"]["body"] == "Nouveau message de Marie-Thérèse Diouf"


@respx.mock
def test_apns_gone_token_is_disabled(respx_mock, push_settings, pere):
    respx_mock.post(f"{APNS_HOST}/3/device/{IOS_TOKEN}").mock(
        return_value=httpx.Response(410, json={"reason": "Unregistered"})
    )
    device = PushDevice.objects.create(user=pere, platform="ios", token=IOS_TOKEN)

    push_deliver_now(device_ids=[device.pk], title="t", body="b", data={})

    device.refresh_from_db()
    assert device.disabled_at is not None


def test_apns_client_speaks_http2(push_settings):
    provider = ApnsProvider.from_settings()

    assert provider is not None
    assert provider.client._transport._pool._http2 is True  # type: ignore[attr-defined]


def test_providers_absent_without_configuration(settings):
    settings.FCM_SERVICE_ACCOUNT_JSON = ""
    settings.FCM_SERVICE_ACCOUNT_FILE = ""
    settings.APNS_PRIVATE_KEY = ""
    settings.APNS_PRIVATE_KEY_FILE = ""

    assert FcmProvider.from_settings() is None
    assert ApnsProvider.from_settings() is None


def test_message_dataclass_defaults():
    assert PushMessage(title="t", body="b").data == {}


# --- Branchement sur les notifications ---------------------------------------------------------------


@respx.mock
def test_notification_send_pushes_with_preferences(
    respx_mock, push_settings, pere, marie, django_capture_on_commit_callbacks
):
    _mock_fcm_token(respx_mock)
    send_route = respx_mock.post(FCM_URL).mock(return_value=httpx.Response(200, json={}))
    PushDevice.objects.create(user=marie, platform="android", token=ANDROID_TOKEN)
    NotificationPreference.objects.create(user=marie, quiet_start=datetime.time(0, 0), quiet_end=datetime.time(0, 0))

    with patch("apps.messaging.services._fanout_notification"), django_capture_on_commit_callbacks(execute=True):
        notification = notification_send(
            user=marie,
            event_type="new_message",
            payload={"conversation_id": "c-1", "sender_id": str(pere.pk), "sender_name": "Emmanuel Tine"},
        )

    body = json.loads(send_route.calls.last.request.content)["message"]
    assert body["notification"]["body"] == "Nouveau message du Père Emmanuel Tine"
    assert body["data"]["notification_id"] == str(notification.pk)
    assert body["android"]["collapse_key"] == str(notification.pk)


def test_push_preference_off_sends_nothing(push_settings, marie, django_capture_on_commit_callbacks):
    PushDevice.objects.create(user=marie, platform="android", token=ANDROID_TOKEN)
    NotificationPreference.objects.create(user=marie, push=False)

    with (
        patch("apps.messaging.services._fanout_notification"),
        patch("apps.messaging.tasks.push_deliver.apply_async") as deliver,
        django_capture_on_commit_callbacks(execute=True),
    ):
        notification_send(user=marie, event_type="documents.status", payload={})

    deliver.assert_not_called()


def test_quiet_hours_defer_the_push(push_settings, marie, django_capture_on_commit_callbacks):
    PushDevice.objects.create(user=marie, platform="android", token=ANDROID_TOKEN)
    NotificationPreference.objects.create(user=marie)  # silence 22 h → 6 h
    late = timezone.make_aware(datetime.datetime(2026, 9, 27, 23, 30))

    with (
        patch("apps.messaging.services_notifications._ws_push"),
        patch("apps.messaging.tasks.push_deliver.apply_async") as deliver,
        django_capture_on_commit_callbacks(execute=True),
    ):
        people_notify(
            user_ids=[marie.pk], topic="annonces", event_type="news.published", payload={"article_id": "a-1"}, now=late
        )

    kwargs = deliver.call_args.kwargs
    assert kwargs["eta"] == timezone.make_aware(datetime.datetime(2026, 9, 28, 6, 0))
    assert kwargs["kwargs"]["body"] == "Nouvelle annonce de votre paroisse."
    assert kwargs["kwargs"]["data"]["article_id"] == "a-1"


def test_push_disabled_globally_sends_nothing(settings, marie, django_capture_on_commit_callbacks):
    settings.PUSH_ENABLED = False
    PushDevice.objects.create(user=marie, platform="android", token=ANDROID_TOKEN)

    with (
        patch("apps.messaging.services._fanout_notification"),
        patch("apps.messaging.tasks.push_deliver.apply_async") as deliver,
        django_capture_on_commit_callbacks(execute=True),
    ):
        notification_send(user=marie, event_type="documents.status", payload={})

    deliver.assert_not_called()


def test_registering_again_reactivates_a_disabled_token(marie):
    device = PushDevice.objects.create(user=marie, platform="android", token=ANDROID_TOKEN, disabled_at=timezone.now())

    push_device_register(user=marie, platform="android", token=ANDROID_TOKEN)

    device.refresh_from_db()
    assert device.disabled_at is None
