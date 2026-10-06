"""PayDunya (agréé au Sénégal) : API « checkout-invoice » (ADR-017).

À VALIDER contre le contrat et la documentation à jour de PayDunya avant la production
(cadrage DONS-00 §5) : chemins, champs de l'IPN et moyen de paiement renvoyé.

- Création : ``POST {base}/checkout-invoice/create`` → ``token`` et URL de paiement.
- Confirmation : ``GET {base}/checkout-invoice/confirm/{token}``.
- IPN : ``POST`` (formulaire ou JSON) dont ``data.hash`` = SHA-512 de la clé maître. Cette
  empreinte étant fixe, la notification n'est jamais crue seule : le service contre-vérifie
  toujours le statut par ``fetch_status`` (serveur à serveur) avant de confirmer un don.

Clés en variables d'environnement uniquement (``PAYDUNYA_MASTER_KEY``, ``PAYDUNYA_PRIVATE_KEY``,
``PAYDUNYA_TOKEN``, ``PAYDUNYA_MODE`` = ``test`` | ``live``).
"""

import datetime
import hashlib
import hmac
import json
import re
from typing import Any
from urllib.parse import parse_qsl

import requests
from django.conf import settings

from apps.donations.enums import PaymentMethod
from apps.donations.providers.base import (
    CheckoutRequest,
    CheckoutSession,
    InvalidSignature,
    PaymentState,
    PayoutData,
    ProviderError,
    ProviderStatus,
)

TIMEOUT = 15
_STATUS = {
    "completed": ProviderStatus.COMPLETED,
    "pending": ProviderStatus.PENDING,
    "cancelled": ProviderStatus.CANCELLED,
    "failed": ProviderStatus.FAILED,
    "expired": ProviderStatus.EXPIRED,
}
_METHODS = {
    "wave": PaymentMethod.WAVE,
    "orange": PaymentMethod.ORANGE_MONEY,
    "free": PaymentMethod.FREE_MONEY,
    "card": PaymentMethod.CARTE,
    "carte": PaymentMethod.CARTE,
}


def _method(value: str) -> str:
    value = (value or "").lower()
    return next((m for key, m in _METHODS.items() if key in value), PaymentMethod.INCONNU)


def _method_from_payload(data: dict[str, Any]) -> str:
    """Moyen de paiement effectif depuis le payload PayDunya.

    JB-API-008 : NE PAS utiliser ``data["mode"]`` — c'est l'environnement PayDunya
    (« test »/« live »), jamais le moyen de paiement, d'où un résultat toujours « inconnu ».
    TODO(JB-API-008) : confirmer sur un VRAI paiement sandbox le champ exact qui porte le
    canal (opérateur mobile / carte). D'après les intégrations connues, il remonte dans le
    bloc ``customer`` (``payment_method``) ou au niveau racine ; on essaie ces emplacements
    plausibles dans l'ordre et, à défaut, on reste sur « inconnu » (valeur par défaut robuste,
    jamais bloquante pour la confirmation du don)."""
    customer = data.get("customer") or {}
    invoice = data.get("invoice") or {}
    candidates = [
        customer.get("payment_method"),
        data.get("payment_method"),
        invoice.get("payment_method"),
        data.get("channel"),
        data.get("payment_channel"),
    ]
    for candidate in candidates:
        if candidate:
            resolved = _method(str(candidate))
            if resolved != PaymentMethod.INCONNU:
                return resolved
    return PaymentMethod.INCONNU


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _unflatten(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """``data[invoice][token]=x`` → ``{"data": {"invoice": {"token": "x"}}}``."""
    root: dict[str, Any] = {}
    for key, value in pairs:
        parts = re.findall(r"[^\[\]]+", key)
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        if parts:
            node[parts[-1]] = value
    return root


class PayDunyaProvider:
    code = "paydunya"

    def __init__(self) -> None:
        self.master_key = settings.PAYDUNYA_MASTER_KEY
        self.private_key = settings.PAYDUNYA_PRIVATE_KEY
        self.token = settings.PAYDUNYA_TOKEN
        live = settings.PAYDUNYA_MODE == "live"
        self.base = "https://app.paydunya.com/api/v1" if live else "https://app.paydunya.com/sandbox-api/v1"
        if not (self.master_key and self.private_key and self.token):
            raise ProviderError("PayDunya n'est pas configuré (variables PAYDUNYA_*).")

    def _headers(self) -> dict[str, str]:
        return {
            "PAYDUNYA-MASTER-KEY": self.master_key,
            "PAYDUNYA-PRIVATE-KEY": self.private_key,
            "PAYDUNYA-TOKEN": self.token,
            "Content-Type": "application/json",
        }

    def _call(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = requests.request(
                method, f"{self.base}/{path}", headers=self._headers(), json=payload, timeout=TIMEOUT
            )
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ProviderError("PayDunya injoignable.") from exc
        if not isinstance(data, dict):
            raise ProviderError("Réponse PayDunya inattendue.")
        return data

    def create_checkout(self, request: CheckoutRequest) -> CheckoutSession:
        data = self._call(
            "POST",
            "checkout-invoice/create",
            {
                "invoice": {"total_amount": request.amount, "description": request.description},
                "store": {"name": settings.DONATIONS_STORE_NAME},
                "actions": {
                    "return_url": request.return_url,
                    "cancel_url": request.cancel_url,
                    "callback_url": request.callback_url,
                },
                "custom_data": {"reference": request.reference, "allocation_key": request.allocation_key},
            },
        )
        if data.get("response_code") != "00" or not data.get("token"):
            raise ProviderError("PayDunya a refusé la création du paiement.")
        return CheckoutSession(
            external_ref=str(data["token"]), checkout_url=str(data.get("response_text", "")), raw=json.dumps(data)
        )

    def verify_callback(self, *, headers: dict[str, str], body: bytes) -> PaymentState:
        text = body.decode(errors="replace")
        try:
            payload = json.loads(text)
        except ValueError:
            payload = _unflatten(parse_qsl(text, keep_blank_values=True))
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        expected = hashlib.sha512(self.master_key.encode()).hexdigest()
        if not hmac.compare_digest(str(data.get("hash", "")), expected):
            raise InvalidSignature("Empreinte PayDunya invalide.")
        invoice = data.get("invoice") or {}
        return PaymentState(
            external_ref=str(invoice.get("token", "")),
            status=_STATUS.get(str(data.get("status", "")).lower(), ProviderStatus.PENDING),
            amount=_to_int(invoice.get("total_amount")),
            method=_method_from_payload(data),
            raw=text,
        )

    def fetch_status(self, *, external_ref: str) -> PaymentState:
        data = self._call("GET", f"checkout-invoice/confirm/{external_ref}")
        invoice = data.get("invoice") or {}
        return PaymentState(
            external_ref=external_ref,
            status=_STATUS.get(str(data.get("status", "")).lower(), ProviderStatus.PENDING),
            amount=_to_int(invoice.get("total_amount")),
            method=_method_from_payload(data),
            raw=json.dumps(data),
        )

    def list_payouts(self, *, since: datetime.datetime) -> list[PayoutData]:
        # Pas d'API de relevé des reversements confirmée à ce jour : rapprochement manuel
        # (import du relevé) tant que le contrat ne la précise pas.
        return []
