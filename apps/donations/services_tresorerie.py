"""Dons : écritures de trésorerie (V2 §5.2) — dépôt bancaire des espèces et remise à la curie.

Ni un dépôt ni une remise ne sont des dons : ils ne changent aucun total « collecté ». Ils
suivent l'argent après la collecte (02-finance §1.1, étapes I et J).
"""

import datetime
from typing import Any

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.donations import access
from apps.donations.enums import (
    CashCollectionStatus,
    DonationChannel,
    DonationStatus,
    FundKind,
    RemittanceMode,
    RemittanceStatus,
)
from apps.donations.models import CashCollection, CashDeposit, CuriaRemittance, Donation, Fund
from apps.hierarchy import authz
from apps.hierarchy.audit import audit_log
from apps.hierarchy.models import Node

# --- Dépôt bancaire des espèces -------------------------------------------------------------


@transaction.atomic
def cash_deposit_declare(
    *,
    actor: Any,
    node: Node,
    collection_ids: list[int],
    deposited_on: datetime.date,
    bank_label: str,
    slip_number: str,
    note: str = "",
) -> CashDeposit:
    """Déclare le dépôt en banque de quêtes validées. Le montant est leur somme (jamais saisi)."""
    access.require_parish_level(actor, "dons.gerer_fonds", node)
    ids = sorted(set(collection_ids))
    if not ids:
        raise ApplicationError("Choisissez au moins une quête à déposer.", code="no_collection")
    collections = list(CashCollection.objects.select_for_update().filter(pk__in=ids, node=node))
    if len(collections) != len(ids):
        raise ApplicationError("Une quête choisie n'appartient pas à la paroisse.", code="collection_outside")
    if any(c.status != CashCollectionStatus.VALIDEE for c in collections):
        raise ApplicationError("Seules les quêtes validées se déposent.", code="collection_not_validated")
    if any(c.deposit_id is not None for c in collections):
        raise ApplicationError("Une quête choisie est déjà déposée.", code="collection_already_deposited")
    if deposited_on > timezone.localdate():
        raise ApplicationError("Le dépôt ne peut pas être à venir.", code="future_deposit")
    if deposited_on < max(c.mass_date for c in collections):
        raise ApplicationError("Le dépôt suit la messe.", code="deposit_before_mass")
    slip = slip_number.strip()
    if not slip or not bank_label.strip():
        raise ApplicationError("La banque et le numéro de bordereau sont obligatoires.", code="slip_required")
    if CashDeposit.objects.filter(node=node, slip_number=slip).exists():
        raise ApplicationError("Ce bordereau est déjà enregistré.", code="slip_duplicate")
    deposit = CashDeposit.objects.create(
        node=node,
        deposited_on=deposited_on,
        bank_label=bank_label.strip(),
        slip_number=slip,
        amount=sum(c.amount for c in collections),
        note=note.strip()[:300],
        declared_by=actor,
    )
    CashCollection.objects.filter(pk__in=ids).update(deposit=deposit)
    audit_log(actor=actor, action="dons.depot_especes", target=deposit, node=node, metadata={"quetes": len(ids)})
    return deposit


# --- Remise à la curie (quête impérée) ------------------------------------------------------


def imperee_cash_to_remit(*, fund: Fund, exclude_pk: Any = None) -> int:
    """Espèces validées de la déclinaison paroissiale, moins les remises déclarées ou confirmées."""
    cash = (
        Donation.objects.filter(fund=fund, channel=DonationChannel.ESPECES, status=DonationStatus.CONFIRME).aggregate(
            s=Sum("net_amount")
        )["s"]
        or 0
    )
    remitted = (
        CuriaRemittance.objects.filter(fund=fund)
        .exclude(status=RemittanceStatus.CONTESTEE)
        .exclude(pk=exclude_pk)
        .aggregate(s=Sum("amount"))["s"]
        or 0
    )
    return int(cash) - int(remitted)


@transaction.atomic
def curia_remittance_declare(
    *,
    actor: Any,
    fund: Fund,
    amount: int,
    remitted_on: datetime.date,
    mode: str = RemittanceMode.ESPECES,
    reference: str = "",
) -> CuriaRemittance:
    """La paroisse déclare avoir remis à la curie les espèces d'une quête impérée."""
    fund = Fund.objects.select_for_update().select_related("node__type").get(pk=fund.pk)
    if fund.kind != FundKind.QUETE_IMPEREE or fund.parent_id is None:
        raise ApplicationError("La remise concerne la quête impérée d'une paroisse.", code="not_an_imperee")
    access.require_parish_level(actor, "dons.gerer_fonds", fund.node)
    if mode not in RemittanceMode.values:
        raise ApplicationError("Mode de remise inconnu.", code="invalid_mode")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ApplicationError("Montant invalide.", code="invalid_amount")
    if remitted_on > timezone.localdate():
        raise ApplicationError("La remise ne peut pas être à venir.", code="future_remittance")
    remaining = imperee_cash_to_remit(fund=fund)
    if amount > remaining:
        raise ApplicationError(
            "Le montant dépasse les espèces de la quête restant à remettre.",
            {"reste": remaining},
            code="remittance_exceeds_cash",
        )
    remittance = CuriaRemittance.objects.create(
        fund=fund,
        node=fund.node,
        amount=amount,
        remitted_on=remitted_on,
        mode=mode,
        reference=reference.strip()[:120],
        declared_by=actor,
    )
    audit_log(actor=actor, action="dons.remise_curie_declaration", target=remittance, node=fund.node,
              metadata={"mode": mode})  # fmt: skip
    return remittance


def _curia(remittance: CuriaRemittance) -> Node | None:
    """Diocèse de la quête impérée (nœud du fonds parent)."""
    parent = remittance.fund.parent
    return parent.node if parent is not None else None


def _require_curia(actor: Any, remittance: CuriaRemittance) -> None:
    diocese = _curia(remittance)
    if diocese is None or not authz.peut(actor, "dons.definir_quete_imperee", diocese):
        raise PermissionDeniedError("Réservé à la curie du diocèse.", code="dons_forbidden")
    authz.mfa_check(actor)
    if remittance.declared_by_id == actor.pk:
        raise ApplicationError("La réception est confirmée par une autre personne.", code="four_eyes")
    if remittance.status != RemittanceStatus.DECLAREE:
        raise ApplicationError("Cette remise est déjà traitée.", code="invalid_transition")


def _locked(remittance: CuriaRemittance) -> CuriaRemittance:
    return (
        CuriaRemittance.objects.select_for_update(of=("self",))
        .select_related("fund__parent__node", "node")
        .get(pk=remittance.pk)
    )


@transaction.atomic
def curia_remittance_confirm(*, remittance: CuriaRemittance, actor: Any) -> CuriaRemittance:
    """La curie confirme avoir reçu la remise."""
    remittance = _locked(remittance)
    _require_curia(actor, remittance)
    remittance.status = RemittanceStatus.CONFIRMEE
    remittance.confirmed_by = actor
    remittance.confirmed_at = timezone.now()
    remittance.save(update_fields=["status", "confirmed_by", "confirmed_at", "updated_at"])
    audit_log(actor=actor, action="dons.remise_curie_confirmation", target=remittance,
              node=_curia(remittance))  # fmt: skip
    return remittance


@transaction.atomic
def curia_remittance_contest(*, remittance: CuriaRemittance, actor: Any, reason: str) -> CuriaRemittance:
    """La curie conteste une remise (montant non reçu, écart) : elle ne compte plus comme remise."""
    remittance = _locked(remittance)
    _require_curia(actor, remittance)
    if not reason.strip():
        raise ApplicationError("Le motif est obligatoire.", code="reason_required")
    remittance.status = RemittanceStatus.CONTESTEE
    remittance.confirmed_by = actor
    remittance.confirmed_at = timezone.now()
    remittance.rejection_reason = reason.strip()[:300]
    remittance.save(update_fields=["status", "confirmed_by", "confirmed_at", "rejection_reason", "updated_at"])
    audit_log(actor=actor, action="dons.remise_curie_contestation", target=remittance,
              node=_curia(remittance))  # fmt: skip
    return remittance
