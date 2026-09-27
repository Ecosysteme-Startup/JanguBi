"""Interface d'un agrégateur de paiement agréé BCEAO (ADR-017).

Jàngu Bi ne voit jamais un numéro de carte ni un code de portefeuille : il crée une session de
paiement, redirige le donateur vers la page de l'agrégateur, puis attend la notification signée.
"""

import datetime
from dataclasses import dataclass, field
from typing import Protocol

from apps.donations.enums import PaymentMethod


class ProviderError(Exception):
    """L'agrégateur est injoignable ou a refusé la demande."""


class InvalidSignature(Exception):
    """La notification n'est pas signée par l'agrégateur."""


class ProviderStatus:
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(frozen=True)
class CheckoutRequest:
    reference: str
    amount: int  # montant payé (FCFA)
    description: str
    return_url: str
    cancel_url: str
    callback_url: str
    allocation_key: str = ""
    customer_email: str = ""


@dataclass(frozen=True)
class CheckoutSession:
    external_ref: str
    checkout_url: str
    expires_at: datetime.datetime | None = None
    raw: str = ""


@dataclass(frozen=True)
class PaymentState:
    external_ref: str
    status: str  # ProviderStatus
    amount: int | None = None
    fee_amount: int | None = None
    method: str = PaymentMethod.INCONNU
    raw: str = ""


@dataclass(frozen=True)
class PayoutData:
    external_ref: str
    paid_at: datetime.datetime
    gross_amount: int
    fee_amount: int
    net_amount: int
    lines: list[tuple[str, int, int]] = field(default_factory=list)  # (external_ref, montant, frais)


class PaymentProvider(Protocol):
    code: str

    def create_checkout(self, request: CheckoutRequest) -> CheckoutSession: ...

    def verify_callback(self, *, headers: dict[str, str], body: bytes) -> PaymentState:
        """Vérifie la signature et décode la notification ; lève ``InvalidSignature``."""
        ...

    def fetch_status(self, *, external_ref: str) -> PaymentState: ...

    def list_payouts(self, *, since: datetime.datetime) -> list[PayoutData]: ...
