"""Dons : clôture mensuelle, écritures d'ajustement et régularisation des incidents de paiement (V2 §5.5).

Un mois clos est figé : aucune quête ne s'y saisit ni ne s'y valide (``services.month_open_check``) ;
un remboursement ou une erreur se corrige par une écriture d'ajustement datée du jour.
"""

import datetime
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.exceptions import ApplicationError
from apps.donations import access
from apps.donations.enums import (
    AdjustmentKind,
    AttemptStatus,
    CashCollectionStatus,
    DonationChannel,
    DonationStatus,
    IncidentKind,
    IncidentResolution,
    IncidentStatus,
    StatusSource,
)
from apps.donations.models import (
    CashCollection,
    Donation,
    DonationActivation,
    DonationAdjustment,
    DonationStatusChange,
    Fund,
    MonthClosing,
    PaymentIncident,
)
from apps.donations.selectors_analyse import month_totals
from apps.hierarchy.audit import audit_log
from apps.hierarchy.models import Node

# --- Clôture mensuelle ----------------------------------------------------------------------


@transaction.atomic
def month_close(*, node: Node, month: datetime.date, actor: Any = None) -> MonthClosing:
    """Clôt un mois écoulé d'une paroisse et fige ses totaux. ``actor`` absent : clôture automatique."""
    if actor is not None:
        access.require_parish_level(actor, "dons.gerer_fonds", node)
    elif not access.is_parish(node):
        raise ApplicationError("Ce nœud n'est pas une paroisse.", code="not_a_parish")
    first = month.replace(day=1)
    if first >= timezone.localdate().replace(day=1):
        raise ApplicationError("Seul un mois écoulé se clôt.", code="month_not_over")
    pending = CashCollection.objects.filter(
        node=node, status=CashCollectionStatus.SAISIE, mass_date__gte=first,
        mass_date__lt=(first + datetime.timedelta(days=32)).replace(day=1),
    ).count()  # fmt: skip
    if pending:
        raise ApplicationError(
            "Des quêtes de ce mois restent à confirmer.", {"quetes": pending}, code="month_has_pending_cash"
        )
    try:
        with transaction.atomic():
            closing = MonthClosing.objects.create(
                node=node, month=first, closed_by=actor, totals=month_totals(node=node, month=first)
            )
    except IntegrityError as exc:
        raise ApplicationError("Ce mois est déjà clos.", code="month_already_closed") from exc
    audit_log(actor=actor, action="dons.cloture_mois", target=closing, node=node, metadata={"mois": f"{first:%Y-%m}"})
    return closing


def months_auto_close(*, today: datetime.date | None = None) -> int:
    """Tâche quotidienne : à partir du jour ``DONATIONS_MONTH_CLOSE_DAY``, clôt le mois précédent des
    paroisses ouvertes qui n'ont plus de quête à confirmer. Idempotente."""
    today = today or timezone.localdate()
    if today.day < settings.DONATIONS_MONTH_CLOSE_DAY:
        return 0
    previous = (today.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
    closed = 0
    for activation in DonationActivation.objects.filter(enabled=True).select_related("node__type"):
        if MonthClosing.objects.filter(node=activation.node, month=previous).exists():
            continue
        try:
            month_close(node=activation.node, month=previous)
        except ApplicationError:
            continue  # quêtes à confirmer : la clôture attend, l'élément reste « à traiter »
        closed += 1
    return closed


# --- Écriture d'ajustement ------------------------------------------------------------------


@transaction.atomic
def adjustment_create(*, actor: Any, fund: Fund, channel: str, amount: int, reason: str) -> DonationAdjustment:
    """Correction d'un mois clos : écriture signée datée du jour, sur le fonds concerné (c. 1267 §3)."""
    access.require_parish_level(actor, "dons.gerer_fonds", fund.node)
    if not access.is_parish(fund.node):
        raise ApplicationError("On ajuste le fonds d'une paroisse.", code="not_a_parish_fund")
    if channel not in DonationChannel.values:
        raise ApplicationError("Canal inconnu.", code="invalid_channel")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount == 0:
        raise ApplicationError("Le montant est un entier non nul (négatif pour retirer).", code="invalid_amount")
    if not reason.strip():
        raise ApplicationError("Le motif est obligatoire.", code="reason_required")
    adjustment = DonationAdjustment.objects.create(
        node=fund.node, fund=fund, kind=AdjustmentKind.CORRECTION, channel=channel, amount=amount,
        net_amount=amount, value_date=timezone.localdate(), reason=reason.strip()[:300], created_by=actor,
    )  # fmt: skip
    audit_log(actor=actor, action="dons.ajustement", target=adjustment, node=fund.node,
              metadata={"canal": channel, "signe": "+" if amount > 0 else "-"})  # fmt: skip
    return adjustment


# --- Incidents de paiement ------------------------------------------------------------------


@transaction.atomic
def incident_resolve(*, incident: PaymentIncident, actor: Any, resolution: str, note: str = "") -> PaymentIncident:
    """Régularise un incident. ``integre`` (paiement tardif seulement) confirme le don, daté du jour :
    le fidèle a bien payé, l'argent va à son fonds. ``rembourse`` : remboursé chez l'agrégateur."""
    incident = (
        PaymentIncident.objects.select_for_update(of=("self",))
        .select_related("donation__fund__node")
        .get(pk=incident.pk)
    )
    node = incident.donation.fund.node
    access.require_parish_level(actor, "dons.gerer_fonds", node)
    if incident.status != IncidentStatus.OUVERT:
        raise ApplicationError("Cet incident est déjà régularisé.", code="invalid_transition")
    if resolution not in IncidentResolution.values:
        raise ApplicationError("Régularisation inconnue.", code="invalid_resolution")
    if resolution == IncidentResolution.INTEGRE:
        if incident.kind != IncidentKind.LATE_PAYMENT:
            raise ApplicationError("Seul un paiement tardif s'intègre au fonds.", code="not_a_late_payment")
        _late_payment_integrate(incident=incident, actor=actor)
    incident.status = IncidentStatus.RESOLU
    incident.resolution = resolution
    incident.note = note.strip()[:300]
    incident.resolved_by = actor
    incident.resolved_at = timezone.now()
    incident.save(update_fields=["status", "resolution", "note", "resolved_by", "resolved_at", "updated_at"])
    audit_log(actor=actor, action="dons.incident_regularisation", target=incident, node=node,
              metadata={"type": incident.kind, "regularisation": resolution})  # fmt: skip
    return incident


def _late_payment_integrate(*, incident: PaymentIncident, actor: Any) -> None:
    """Seule sortie d'un statut terminal (``expire`` / ``echoue``) vers ``confirme`` : décidée par la
    paroisse sur un paiement que l'agrégateur a bien encaissé, et journalisée."""
    from apps.donations.services import _receipt_number_next  # import local : évite un cycle

    donation = Donation.objects.select_for_update().select_related("fund__node").get(pk=incident.donation_id)
    if donation.status not in (DonationStatus.EXPIRE, DonationStatus.ECHOUE):
        raise ApplicationError("Ce don n'est plus à régulariser.", code="invalid_transition")
    now = timezone.now()
    DonationStatusChange.objects.create(
        donation=donation, from_status=donation.status, to_status=DonationStatus.CONFIRME,
        source=StatusSource.STAFF, actor=actor, note="paiement tardif intégré",
    )  # fmt: skip
    donation.status = DonationStatus.CONFIRME
    donation.status_changed_at = now
    donation.confirmed_at = now
    donation.value_date = timezone.localdate(now)
    if not donation.receipt_number:
        donation.receipt_number = _receipt_number_next(node=donation.fund.node, year=donation.value_date.year)
    donation.save(update_fields=["status", "status_changed_at", "confirmed_at", "value_date", "receipt_number",
                                 "updated_at"])  # fmt: skip
    incident.attempt.status = AttemptStatus.REUSSI
    incident.attempt.save(update_fields=["status", "updated_at"])
