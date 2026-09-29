"""Fournisseurs de notifications push : FCM HTTP v1 (compte de service) et APNs (jeton JWT, HTTP/2).

Aucune dépendance Google ni Apple : les deux jetons d'accès sont signés avec PyJWT et les
appels passent par httpx (HTTP/2 pour APNs, paquet ``h2``). Chaque envoi renvoie un
``PushOutcome`` : réussi, jeton invalide (à désactiver) ou erreur passagère (à réessayer).
"""

import json
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
import jwt
from django.conf import settings
from django.core.cache import cache

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
FCM_SEND_URL = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"
FCM_TOKEN_CACHE_KEY = "push:fcm:access-token"
APNS_HOST = "https://api.push.apple.com"
APNS_SANDBOX_HOST = "https://api.sandbox.push.apple.com"
APNS_JWT_LIFETIME = 50 * 60  # Apple : entre 20 et 60 minutes
APNS_TOKEN_RE = re.compile(r"^[0-9a-fA-F]{64}$")

FCM_INVALID_CODES = frozenset({"UNREGISTERED", "SENDER_ID_MISMATCH"})
APNS_INVALID_REASONS = frozenset({"BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"})


@dataclass(frozen=True)
class PushMessage:
    title: str
    body: str
    data: dict[str, str] = field(default_factory=dict)
    collapse_id: str = ""


@dataclass(frozen=True)
class PushOutcome:
    ok: bool
    invalid_token: bool = False
    retryable: bool = False
    detail: str = ""


class PushProvider(Protocol):
    name: str

    def send(self, *, token: str, message: PushMessage) -> PushOutcome: ...


def _retryable(status: int) -> bool:
    return status == 429 or status >= 500


# --- FCM HTTP v1 -------------------------------------------------------------------------------


class FcmProvider:
    name = "fcm"

    def __init__(self, *, project_id: str, service_account: dict[str, Any], client: httpx.Client | None = None):
        self.project_id = project_id
        self.service_account = service_account
        self.client = client or httpx.Client(timeout=settings.PUSH_HTTP_TIMEOUT_SECONDS)

    @classmethod
    def from_settings(cls) -> "FcmProvider | None":
        raw = settings.FCM_SERVICE_ACCOUNT_JSON
        if not raw and settings.FCM_SERVICE_ACCOUNT_FILE:
            with open(settings.FCM_SERVICE_ACCOUNT_FILE, encoding="utf-8") as fh:
                raw = fh.read()
        if not raw:
            return None
        account = json.loads(raw)
        project = settings.FCM_PROJECT_ID or account.get("project_id", "")
        if not project:
            return None
        return cls(project_id=project, service_account=account)

    def _access_token(self) -> str:
        token = cache.get(FCM_TOKEN_CACHE_KEY)
        if token:
            return token
        now = int(time.time())
        token_uri = self.service_account.get("token_uri", "https://oauth2.googleapis.com/token")
        assertion = jwt.encode(
            {
                "iss": self.service_account["client_email"],
                "scope": FCM_SCOPE,
                "aud": token_uri,
                "iat": now,
                "exp": now + 3600,
            },
            self.service_account["private_key"],
            algorithm="RS256",
            headers={"kid": self.service_account.get("private_key_id", "")},
        )
        response = self.client.post(
            token_uri,
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
        )
        response.raise_for_status()
        payload = response.json()
        token = payload["access_token"]
        cache.set(FCM_TOKEN_CACHE_KEY, token, max(int(payload.get("expires_in", 3600)) - 300, 60))
        return token

    def _body(self, *, token: str, message: PushMessage) -> dict[str, Any]:
        android: dict[str, Any] = {
            "priority": "high",
            "notification": {"channel_id": settings.FCM_ANDROID_CHANNEL_ID},
        }
        apns: dict[str, Any] = {"payload": {"aps": {"sound": "default"}}}
        if message.collapse_id:
            android["collapse_key"] = message.collapse_id[:64]
            apns["headers"] = {"apns-collapse-id": message.collapse_id[:64]}
        return {
            "message": {
                "token": token,
                "notification": {"title": message.title, "body": message.body},
                "data": message.data,
                "android": android,
                "apns": apns,
            }
        }

    def send(self, *, token: str, message: PushMessage) -> PushOutcome:
        try:
            access = self._access_token()
            response = self.client.post(
                FCM_SEND_URL.format(project=self.project_id),
                headers={"Authorization": f"Bearer {access}"},
                json=self._body(token=token, message=message),
            )
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            return PushOutcome(ok=False, retryable=True, detail=f"fcm:{type(exc).__name__}")
        if response.status_code == 200:
            return PushOutcome(ok=True)
        code = _fcm_error_code(response)
        if response.status_code == 401:
            cache.delete(FCM_TOKEN_CACHE_KEY)
            return PushOutcome(ok=False, retryable=True, detail="fcm:401")
        if response.status_code == 404 or code in FCM_INVALID_CODES:
            return PushOutcome(ok=False, invalid_token=True, detail=f"fcm:{code or response.status_code}")
        return PushOutcome(
            ok=False, retryable=_retryable(response.status_code), detail=f"fcm:{code or response.status_code}"
        )


def _fcm_error_code(response: httpx.Response) -> str:
    try:
        error = response.json().get("error", {})
    except ValueError:
        return ""
    for detail in error.get("details", []) or []:
        if detail.get("errorCode"):
            return str(detail["errorCode"])
    return str(error.get("status", ""))


# --- APNs (jeton JWT ES256, HTTP/2) ------------------------------------------------------------


class ApnsProvider:
    name = "apns"
    _lock = threading.Lock()

    def __init__(
        self,
        *,
        team_id: str,
        key_id: str,
        private_key: str,
        topic: str,
        sandbox: bool = False,
        client: httpx.Client | None = None,
    ):
        self.team_id = team_id
        self.key_id = key_id
        self.private_key = private_key
        self.topic = topic
        self.host = APNS_SANDBOX_HOST if sandbox else APNS_HOST
        self.client = client or httpx.Client(http2=True, timeout=settings.PUSH_HTTP_TIMEOUT_SECONDS)
        self._jwt: tuple[str, float] | None = None

    @classmethod
    def from_settings(cls) -> "ApnsProvider | None":
        key = settings.APNS_PRIVATE_KEY
        if not key and settings.APNS_PRIVATE_KEY_FILE:
            with open(settings.APNS_PRIVATE_KEY_FILE, encoding="utf-8") as fh:
                key = fh.read()
        if not (key and settings.APNS_TEAM_ID and settings.APNS_KEY_ID and settings.APNS_TOPIC):
            return None
        return cls(
            team_id=settings.APNS_TEAM_ID,
            key_id=settings.APNS_KEY_ID,
            private_key=key,
            topic=settings.APNS_TOPIC,
            sandbox=settings.APNS_USE_SANDBOX,
        )

    def _provider_token(self) -> str:
        with self._lock:
            now = time.time()
            if self._jwt is None or now - self._jwt[1] > APNS_JWT_LIFETIME:
                token = jwt.encode(
                    {"iss": self.team_id, "iat": int(now)},
                    self.private_key,
                    algorithm="ES256",
                    headers={"kid": self.key_id},
                )
                self._jwt = (token, now)
            return self._jwt[0]

    def send(self, *, token: str, message: PushMessage) -> PushOutcome:
        headers = {
            "authorization": f"bearer {self._provider_token()}",
            "apns-topic": self.topic,
            "apns-push-type": "alert",
            "apns-priority": "10",
        }
        if message.collapse_id:
            headers["apns-collapse-id"] = message.collapse_id[:64]
        body = {"aps": {"alert": {"title": message.title, "body": message.body}, "sound": "default"}, **message.data}
        try:
            response = self.client.post(f"{self.host}/3/device/{token}", headers=headers, json=body)
        except httpx.HTTPError as exc:
            return PushOutcome(ok=False, retryable=True, detail=f"apns:{type(exc).__name__}")
        if response.status_code == 200:
            return PushOutcome(ok=True)
        try:
            reason = str(response.json().get("reason", ""))
        except ValueError:
            reason = ""
        if response.status_code == 410 or reason in APNS_INVALID_REASONS:
            return PushOutcome(ok=False, invalid_token=True, detail=f"apns:{reason or response.status_code}")
        if reason == "ExpiredProviderToken":
            self._jwt = None
            return PushOutcome(ok=False, retryable=True, detail="apns:ExpiredProviderToken")
        return PushOutcome(
            ok=False, retryable=_retryable(response.status_code), detail=f"apns:{reason or response.status_code}"
        )


# --- Choix du fournisseur ------------------------------------------------------------------------


def is_apns_token(token: str) -> bool:
    """Jeton APNs natif (64 caractères hexadécimaux). Un jeton FCM, même d'un iPhone, n'y ressemble pas."""
    return bool(APNS_TOKEN_RE.match(token))


def provider_for(
    *, platform: str, token: str, fcm: PushProvider | None, apns: PushProvider | None
) -> PushProvider | None:
    if platform == "ios" and is_apns_token(token):
        return apns
    return fcm
