"""Agrégateur factice pour les tests, la CI et la démonstration locale. Jamais en production.

État des paiements dans le cache Django (partagé entre processus avec Redis en local).
Signature des notifications : HMAC-SHA256 du corps avec ``DONATIONS_FAKE_SECRET``,
dans l'en-tête ``X-Fake-Signature``.
"""

import datetime
import hashlib
import hmac
import json
import secrets
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.donations.enums import PaymentMethod
from apps.donations.providers.base import (
    CheckoutRequest,
    CheckoutSession,
    InvalidSignature,
    PaymentState,
    PayoutData,
    ProviderStatus,
)

SIGNATURE_HEADER = "X-Fake-Signature"
_STATE_KEY = "dons:fake:state:{}"
_PAYOUTS_KEY = "dons:fake:payouts"
_TTL = 7 * 24 * 3600


def _secret() -> bytes:
    return str(getattr(settings, "DONATIONS_FAKE_SECRET", "fake-secret")).encode()


def sign(body: bytes) -> str:
    return hmac.new(_secret(), body, hashlib.sha256).hexdigest()


class FakeProvider:
    code = "fake"

    def create_checkout(self, request: CheckoutRequest) -> CheckoutSession:
        token = f"fake_{secrets.token_hex(8)}"
        cache.set(
            _STATE_KEY.format(token),
            {"status": ProviderStatus.PENDING, "amount": request.amount, "method": PaymentMethod.INCONNU, "fee": None},
            _TTL,
        )
        base = getattr(settings, "DONATIONS_FAKE_CHECKOUT_BASE", "https://paiement.exemple.test/checkout")
        return CheckoutSession(
            external_ref=token,
            checkout_url=f"{base}/{token}",
            expires_at=timezone.now() + datetime.timedelta(hours=1),
            raw=json.dumps({"token": token, "reference": request.reference}),
        )

    def verify_callback(self, *, headers: dict[str, str], body: bytes) -> PaymentState:
        received = {k.lower(): v for k, v in headers.items()}.get(SIGNATURE_HEADER.lower(), "")
        if not received or not hmac.compare_digest(received, sign(body)):
            raise InvalidSignature("Signature absente ou invalide.")
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise InvalidSignature("Corps illisible.") from exc
        return PaymentState(
            external_ref=str(data.get("token", "")),
            status=str(data.get("status", "")),
            amount=data.get("amount"),
            fee_amount=data.get("fee"),
            method=str(data.get("method") or PaymentMethod.INCONNU),
            raw=body.decode(errors="replace"),
        )

    def fetch_status(self, *, external_ref: str) -> PaymentState:
        state = cache.get(_STATE_KEY.format(external_ref)) or {"status": ProviderStatus.EXPIRED}
        return PaymentState(
            external_ref=external_ref,
            status=state["status"],
            amount=state.get("amount"),
            fee_amount=state.get("fee"),
            method=state.get("method") or PaymentMethod.INCONNU,
            raw=json.dumps(state),
        )

    def list_payouts(self, *, since: datetime.datetime) -> list[PayoutData]:
        return [p for p in cache.get(_PAYOUTS_KEY, []) if p.paid_at >= since]

    # --- Pilotage (tests et démonstration) --------------------------------------------------

    @staticmethod
    def simulate(
        external_ref: str,
        status: str,
        *,
        amount: int | None = None,
        method: str = PaymentMethod.WAVE,
        fee: int | None = None,
    ) -> tuple[dict[str, str], bytes]:
        """Fixe l'état côté « agrégateur » et renvoie (en-têtes, corps) de la notification signée."""
        key = _STATE_KEY.format(external_ref)
        state: dict[str, Any] = cache.get(key) or {}
        state.update({"status": status, "method": method, "fee": fee})
        if amount is not None:
            state["amount"] = amount
        cache.set(key, state, _TTL)
        body = json.dumps(
            {"token": external_ref, "status": status, "amount": state.get("amount"), "method": method, "fee": fee}
        ).encode()
        return {SIGNATURE_HEADER: sign(body)}, body

    @staticmethod
    def add_payout(payout: PayoutData) -> None:
        cache.set(_PAYOUTS_KEY, [*cache.get(_PAYOUTS_KEY, []), payout], _TTL)

    @staticmethod
    def reset() -> None:
        cache.delete(_PAYOUTS_KEY)
