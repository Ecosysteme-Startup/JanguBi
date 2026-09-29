"""Dons et quêtes : toutes les lectures (ADR-017). Aucune écriture.

Anonymat et agrégats : les sélecteurs publics et diocésains ne renvoient que des totaux ; le
masquage des noms est décidé par l'appelant (capacité ``dons.voir_donateurs``).
"""

import datetime
from typing import Any
from uuid import UUID

from django.db.models import Count, Min, Q, QuerySet, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.core.exceptions import NotFoundError
from apps.donations.enums import (
    CashCollectionStatus,
    DonationChannel,
    DonationStatus,
    FundKind,
    FundStatus,
    PaymentMethod,
    PayoutStatus,
    RemittanceStatus,
    WebhookStatus,
)
from apps.donations.models import (
    CashCollection,
    CashDeposit,
    CuriaRemittance,
    Donation,
    DonationActivation,
    DonationAdjustment,
    Fund,
    MonthClosing,
    PaymentAttempt,
    PaymentIncident,
    PaymentWebhookEvent,
    Payout,
)
from apps.donations.selectors_analyse import FUND_KIND_ORDER, METHOD_ORDER, Ledger, alpha_key
from apps.hierarchy.models import Node

CONFIRMED = Q(status=DonationStatus.CONFIRME)


def _sum(field: str, condition: Q | None = None) -> Coalesce:
    return Coalesce(Sum(field, filter=condition), 0)


# --- Public ---------------------------------------------------------------------------------


def activation_for(*, node: Node) -> DonationActivation | None:
    return DonationActivation.objects.filter(node=node, enabled=True).first()


def funds_open_for_parish(*, node: Node) -> QuerySet[Fund]:
    today = timezone.localdate()
    return (
        funds_with_totals(Fund.objects.filter(node=node, status=FundStatus.OUVERT))
        .filter(Q(starts_on__isnull=True) | Q(starts_on__lte=today))
        .filter(Q(ends_on__isnull=True) | Q(ends_on__gte=today))
        .order_by("kind", "starts_on", "title")
    )


def funds_with_totals(queryset: QuerySet[Fund]) -> QuerySet[Fund]:
    """Annotation ``raised`` = somme affectée (dons confirmés), ``donations_count``."""
    return queryset.select_related("node", "image", "place").annotate(
        raised=_sum("donations__net_amount", Q(donations__status=DonationStatus.CONFIRME)),
        donations_count=Count("donations", filter=Q(donations__status=DonationStatus.CONFIRME)),
    )


def fund_public_get(*, fund_id: UUID | str) -> Fund:
    """Fonds publié d'une paroisse dont la collecte est active."""
    fund = (
        funds_with_totals(Fund.objects.exclude(status=FundStatus.BROUILLON))
        .filter(pk=fund_id, node__donation_activation__enabled=True)
        .first()
    )
    if fund is None:
        raise NotFoundError("Fonds introuvable.")
    return fund


def fund_updates(*, fund: Fund) -> QuerySet[Any]:
    return fund.updates.select_related("author__profile").order_by("-created_at")


def donation_public_get(*, donation_id: UUID | str) -> Donation:
    donation = Donation.objects.select_related("fund__node").filter(pk=donation_id).first()
    if donation is None:
        raise NotFoundError("Don introuvable.")
    return donation


# --- Fidèle ---------------------------------------------------------------------------------


def donations_for_donor(*, user: Any, fund_id: UUID | None = None, year: int | None = None) -> QuerySet[Donation]:
    qs = (
        Donation.objects.filter(donor=user)
        .exclude(status=DonationStatus.INITIE)
        .select_related("fund__node")
        .order_by("-created_at")
    )
    if fund_id:
        qs = qs.filter(fund_id=fund_id)
    if year:
        qs = qs.filter(created_at__year=year)
    return qs


def donor_summary(*, user: Any, year: int) -> dict[str, Any]:
    """Total de l'année, visible du seul donateur (montant donné, hors frais)."""
    qs = Donation.objects.filter(donor=user, status=DonationStatus.CONFIRME, confirmed_at__year=year)
    by_fund = (
        qs.values("fund_id", "fund__title", "fund__node__name")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("-total")
    )
    totals = qs.aggregate(total=_sum("amount"), count=Count("id"))
    return {
        "year": year,
        "total": totals["total"],
        "count": totals["count"],
        "by_fund": [
            {"fund_id": r["fund_id"], "title": r["fund__title"], "parish": r["fund__node__name"],
             "total": r["total"], "count": r["count"]}
            for r in by_fund
        ],  # fmt: skip
    }


def donation_get_for_donor(*, user: Any, donation_id: UUID | str) -> Donation:
    donation = Donation.objects.select_related("fund__node").filter(pk=donation_id, donor=user).first()
    if donation is None:
        raise NotFoundError("Don introuvable.")
    return donation


# --- Paroisse -------------------------------------------------------------------------------


def fund_get(*, fund_id: UUID | str) -> Fund:
    fund = funds_with_totals(Fund.objects.select_related("node__type")).filter(pk=fund_id).first()
    if fund is None:
        raise NotFoundError("Fonds introuvable.")
    return fund


def funds_for_parish(*, node: Node, status: str | None = None, kind: str | None = None) -> QuerySet[Fund]:
    qs = funds_with_totals(Fund.objects.filter(node=node))
    if status:
        qs = qs.filter(status=status)
    if kind:
        qs = qs.filter(kind=kind)
    return qs.order_by("-created_at")


def _month_bounds(month: datetime.date) -> tuple[datetime.date, datetime.date]:
    start = month.replace(day=1)
    end = (start + datetime.timedelta(days=32)).replace(day=1)
    return start, end


def parish_summary(*, node: Node, month: datetime.date) -> dict[str, Any]:
    """Synthèse du mois (montant affecté) sur la **date de valeur** : jour de la messe pour les espèces,
    date de confirmation en ligne ; remboursements en ligne négative du mois où ils ont lieu.

    Corrections V2 : ``daily`` ventilé par canal ; ``online_count`` et ``cash_collections_count`` (``count``
    reste, obsolète) ; ``by_fund[].destination`` et ``by_destination`` ; ``pending_count`` limité au mois
    avec ``pending_oldest_at`` ; ordre fixe (jamais par montant)."""
    start, end = _month_bounds(month)
    last = end - datetime.timedelta(days=1)
    ledger = Ledger(Q(fund__node=node), start, last, value="net_amount")
    online_q, cash_q = Q(channel=DonationChannel.EN_LIGNE), Q(channel=DonationChannel.ESPECES)
    total, count = ledger.total()
    online, online_count = ledger.total(online_q)
    cash, cash_count = ledger.total(cash_q)
    fees = ledger.donations.filter(online_q).aggregate(s=_sum("fee_amount"))["s"]
    by_fund = sorted(
        ledger.group("fund_id", "fund__title", "fund__kind", "fund__destination"),
        key=lambda r: (FUND_KIND_ORDER.index(r["fund__kind"]) if r["fund__kind"] in FUND_KIND_ORDER else 99,
                       alpha_key(r["fund__title"])),
    )  # fmt: skip
    destinations = {r["fund__destination"]: r["s"] for r in ledger.group("fund__destination")}
    method_order = [*METHOD_ORDER, PaymentMethod.ESPECES]
    by_method = sorted(
        ledger.group("payment_method"),
        key=lambda r: method_order.index(r["payment_method"]) if r["payment_method"] in method_order else 99,
    )
    days: dict[datetime.date, dict[str, int]] = {}
    for r in ledger.group("value_date", "channel"):
        slot = days.setdefault(r["value_date"], {"online": 0, "cash": 0})
        slot["online" if r["channel"] == DonationChannel.EN_LIGNE else "cash"] += r["s"]
    pending = Donation.objects.filter(
        fund__node=node, status__in=[DonationStatus.INITIE, DonationStatus.EN_ATTENTE],
        created_at__date__gte=start, created_at__date__lt=end,
    ).aggregate(n=Count("id"), oldest=Min("created_at"))  # fmt: skip
    cash_to_validate = CashCollection.objects.filter(node=node, status=CashCollectionStatus.SAISIE).count()
    closing = MonthClosing.objects.filter(node=node, month=start).first()
    return {
        "month": start,
        "total": total,
        "online": online,
        "cash": cash,
        "fees": fees,
        "count": count,
        "online_count": online_count,
        "cash_collections_count": cash_count,
        "pending_count": pending["n"],
        "pending_oldest_at": pending["oldest"],
        "cash_to_validate": cash_to_validate,
        "closed": closing is not None,
        "closed_at": closing.created_at if closing else None,
        "by_destination": {"paroisse": destinations.get("paroisse", 0), "curie": destinations.get("curie", 0)},
        "by_fund": [
            {"fund_id": r["fund_id"], "title": r["fund__title"], "kind": r["fund__kind"],
             "destination": r["fund__destination"], "total": r["s"], "count": r["n"]}
            for r in by_fund
        ],  # fmt: skip
        "by_method": [{"method": r["payment_method"], "total": r["s"], "count": r["n"]} for r in by_method],
        "daily": [
            {"date": day, "online": v["online"], "cash": v["cash"], "total": v["online"] + v["cash"]}
            for day, v in sorted(days.items())
        ],
    }


def operations_for_parish(
    *,
    node: Node,
    fund_id: UUID | None = None,
    status: str | None = None,
    channel: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> QuerySet[Donation]:
    qs = (
        Donation.objects.filter(fund__node=node)
        .exclude(status=DonationStatus.INITIE)
        .select_related("fund", "donor__profile", "cash_collection", "place")
        .order_by("-created_at")
    )
    if fund_id:
        qs = qs.filter(fund_id=fund_id)
    if status:
        qs = qs.filter(status=status)
    if channel:
        qs = qs.filter(channel=channel)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    return qs


def operation_get(*, donation_id: UUID | str) -> Donation:
    donation = Donation.objects.select_related("fund__node__type", "donor__profile", "place").filter(pk=donation_id).first()
    if donation is None:
        raise NotFoundError("Opération introuvable.")
    return donation


def funds_for_mass(*, node: Node, mass_date: datetime.date) -> list[Fund]:
    """Fonds proposés pour la saisie de la quête d'une messe : quêtes impérées qui couvrent cette messe
    (messe anticipée comprise si le diocèse l'a décidé), puis les autres fonds ouverts à cette date."""
    from apps.donations.services import imperee_covers  # la règle vit avec la saisie

    funds = (
        Fund.objects.filter(node=node, status=FundStatus.OUVERT)
        .filter(Q(ends_on__isnull=True) | Q(ends_on__gte=mass_date - datetime.timedelta(days=1)))
        .select_related("node", "image", "place")
    )
    imperees = [f for f in funds if f.kind == FundKind.QUETE_IMPEREE and imperee_covers(fund=f, mass_date=mass_date)]
    others = [f for f in funds if f.kind != FundKind.QUETE_IMPEREE and (f.starts_on is None or f.starts_on <= mass_date)
              and (f.ends_on is None or f.ends_on >= mass_date)]  # fmt: skip
    others.sort(key=lambda f: (f.kind != FundKind.QUETE_DOMINICALE, alpha_key(f.title)))
    return imperees + others


def cash_collections_for_parish(*, node: Node, status: str | None = None) -> QuerySet[CashCollection]:
    qs = CashCollection.objects.filter(node=node).select_related(
        "fund", "place", "entered_by__profile", "validated_by__profile"
    )
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-mass_date", "-created_at")


def cash_collection_get(*, collection_id: int) -> CashCollection:
    collection = CashCollection.objects.select_related("node__type", "fund").filter(pk=collection_id).first()
    if collection is None:
        raise NotFoundError("Saisie introuvable.")
    return collection


def parish_reconciliation(*, node: Node, date_from: datetime.date, date_to: datetime.date) -> dict[str, Any]:
    """Rapprochement de la paroisse (H1 : les reversements arrivent au diocèse)."""
    period = Q(confirmed_at__date__gte=date_from, confirmed_at__date__lte=date_to)
    confirmed = Donation.objects.filter(period, fund__node=node, status=DonationStatus.CONFIRME)
    totals = confirmed.aggregate(
        online_charged=_sum("charged_amount", Q(channel=DonationChannel.EN_LIGNE)),
        online_fees=_sum("fee_amount", Q(channel=DonationChannel.EN_LIGNE)),
        online_net=_sum("net_amount", Q(channel=DonationChannel.EN_LIGNE)),
        cash=_sum("net_amount", Q(channel=DonationChannel.ESPECES)),
        paid_out=_sum("net_amount", Q(channel=DonationChannel.EN_LIGNE, payout__isnull=False)),
        awaiting_payout=_sum("net_amount", Q(channel=DonationChannel.EN_LIGNE, payout__isnull=True)),
    )
    issues: list[dict[str, Any]] = []
    stale_limit = timezone.now() - datetime.timedelta(hours=24)
    for d in Donation.objects.filter(
        fund__node=node, status=DonationStatus.EN_ATTENTE, created_at__lt=stale_limit
    ).only("reference", "created_at"):
        issues.append({"kind": "paiement_en_attente", "reference": d.reference, "date": d.created_at.date()})
    for c in CashCollection.objects.filter(
        node=node, status=CashCollectionStatus.SAISIE, mass_date__lte=timezone.localdate() - datetime.timedelta(days=7)
    ):
        issues.append({"kind": "quete_non_validee", "reference": f"Q-{c.pk}", "date": c.mass_date})
    for p in Payout.objects.filter(
        status=PayoutStatus.ECART, lines__attempt__donation__fund__node=node
    ).distinct():
        issues.append({"kind": "reversement_ecart", "reference": p.external_ref, "date": p.paid_at.date()})
    return {"date_from": date_from, "date_to": date_to, **totals, "issues": issues}


def export_rows(
    *, node: Node, date_from: datetime.date, date_to: datetime.date, fund_id: UUID | None = None, with_names: bool
) -> list[dict[str, Any]]:
    qs = (
        Donation.objects.filter(
            fund__node=node,
            status__in=[DonationStatus.CONFIRME, DonationStatus.REMBOURSE],
            confirmed_at__date__gte=date_from,
            confirmed_at__date__lte=date_to,
        )
        .select_related("fund", "donor__profile", "cash_collection", "payout")
        .order_by("confirmed_at")
    )
    if fund_id:
        qs = qs.filter(fund_id=fund_id)
    return [
        {
            "date": timezone.localtime(d.confirmed_at).date().isoformat() if d.confirmed_at else "",
            "recu": d.receipt_number or "",
            "reference": d.reference,
            "fonds": d.fund.title,
            "type": d.fund.get_kind_display(),
            "destination": d.fund.get_destination_display(),
            "canal": d.get_channel_display(),
            "moyen": d.get_payment_method_display(),
            "statut": d.get_status_display(),
            "don": d.amount,
            "frais": d.fee_amount,
            "paye": d.charged_amount,
            "affecte": d.net_amount,
            "donateur": donor_label(d, with_names=with_names),
            "reversement": d.payout.external_ref if d.payout else "",
        }
        for d in qs
    ]


def donor_label(donation: Donation, *, with_names: bool) -> str:
    """Nom affiché d'un donateur. Un don anonyme reste « Anonyme » dans les listes ; seul le curé peut
    consulter le nom, au cas par cas, avec un motif journalisé (``services.donor_reveal``)."""
    if donation.channel == DonationChannel.ESPECES:
        return "Quête en espèces"
    if donation.anonymous:
        return "Anonyme"
    if donation.donor_id is None:
        return "Donateur sans compte"
    if not with_names:
        return "Donateur"
    profile = getattr(donation.donor, "profile", None)
    name = f"{getattr(profile, 'first_name', '')} {getattr(profile, 'last_name', '')}".strip()
    return name or "Donateur"


# --- Diocèse (agrégats uniquement) ----------------------------------------------------------


def imperees_for_diocese(*, diocese: Node) -> QuerySet[Fund]:
    return (
        Fund.objects.filter(node=diocese, kind=FundKind.QUETE_IMPEREE, parent__isnull=True)
        .annotate(
            raised=_sum("parish_funds__donations__net_amount", Q(parish_funds__donations__status=DonationStatus.CONFIRME)),
            parishes_count=Count("parish_funds", distinct=True),
        )
        .order_by("-starts_on", "-created_at")
    )


def imperee_get(*, fund_id: UUID | str) -> Fund:
    fund = (
        Fund.objects.select_related("node__type")
        .filter(pk=fund_id, kind=FundKind.QUETE_IMPEREE, parent__isnull=True)
        .first()
    )
    if fund is None:
        raise NotFoundError("Quête impérée introuvable.")
    return fund


def imperee_follow(*, fund: Fund) -> list[dict[str, Any]]:
    """Par paroisse : en ligne, espèces, nombre de dons, remises à la curie. Aucune donnée nominative.

    Seules les espèces se remettent : la part en ligne est déjà sur le compte de l'économat (H1)."""
    remittances = {
        r["fund_id"]: r
        for r in CuriaRemittance.objects.filter(fund__parent=fund)
        .values("fund_id")
        .annotate(
            confirmed=_sum("amount", Q(status=RemittanceStatus.CONFIRMEE)),
            declared=_sum("amount", Q(status=RemittanceStatus.DECLAREE)),
        )
    }
    rows = (
        Fund.objects.filter(parent=fund)
        .values("id", "node_id", "node__name", "status")
        .annotate(
            online=_sum("donations__net_amount", Q(donations__status=DonationStatus.CONFIRME,
                                                   donations__channel=DonationChannel.EN_LIGNE)),
            cash=_sum("donations__net_amount", Q(donations__status=DonationStatus.CONFIRME,
                                                 donations__channel=DonationChannel.ESPECES)),
            count=Count("donations", filter=Q(donations__status=DonationStatus.CONFIRME)),
        )  # fmt: skip
        .order_by("node__name")
    )
    result = []
    for r in rows:
        rem = remittances.get(r["id"], {"confirmed": 0, "declared": 0})
        result.append(
            {"fund_id": r["id"], "parish_id": r["node_id"], "parish": r["node__name"], "status": r["status"],
             "online": r["online"], "cash": r["cash"], "count": r["count"], "total": r["online"] + r["cash"],
             "remitted_confirmed": rem["confirmed"], "remitted_declared": rem["declared"],
             "to_remit": max(r["cash"] - rem["confirmed"] - rem["declared"], 0), "remit_by": fund.remit_by}
        )  # fmt: skip
    return result


# --- Trésorerie : dépôts et remises ---------------------------------------------------------


def _deposits() -> QuerySet[CashDeposit]:
    return CashDeposit.objects.select_related("declared_by__profile").annotate(collections_count=Count("collections"))


def cash_deposits_for_parish(*, node: Node) -> QuerySet[CashDeposit]:
    return _deposits().filter(node=node).order_by("-deposited_on", "-created_at")


def cash_deposit_get(*, deposit_id: int) -> CashDeposit:
    deposit = _deposits().filter(pk=deposit_id).first()
    if deposit is None:
        raise NotFoundError("Dépôt introuvable.")
    return deposit


def remittances_for(*, node: Node, status: str | None = None) -> QuerySet[CuriaRemittance]:
    """Remises d'une paroisse, ou de toutes les paroisses d'un diocèse (``node`` = diocèse)."""
    qs = CuriaRemittance.objects.filter(node__path__startswith=node.path).select_related(
        "fund", "node", "declared_by__profile", "confirmed_by__profile"
    )
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-remitted_on", "-created_at")


def remittance_get(*, remittance_id: int) -> CuriaRemittance:
    remittance = (
        CuriaRemittance.objects.select_related("fund__parent__node", "node__type", "declared_by__profile",
                                               "confirmed_by__profile")  # fmt: skip
        .filter(pk=remittance_id)
        .first()
    )
    if remittance is None:
        raise NotFoundError("Remise introuvable.")
    return remittance


def payouts_for_diocese(*, diocese: Node) -> QuerySet[Payout]:
    return Payout.objects.filter(node=diocese).order_by("-paid_at")


# --- Plateforme -----------------------------------------------------------------------------


def platform_health(*, now: datetime.datetime | None = None) -> dict[str, Any]:
    """Santé technique de l'intégration : aucun nom ni montant par donateur."""
    now = now or timezone.now()
    day, week = now - datetime.timedelta(hours=24), now - datetime.timedelta(days=7)
    events = PaymentWebhookEvent.objects.all()
    by_status = {
        s: events.filter(received_at__gte=week, status=s).count() for s in WebhookStatus.values
    }
    pending = PaymentAttempt.objects.filter(donation__status=DonationStatus.EN_ATTENTE)
    oldest = pending.order_by("created_at").values_list("created_at", flat=True).first()
    last_event = events.order_by("-received_at").values_list("received_at", flat=True).first()
    incidents = [
        {"at": e.received_at, "provider": e.provider, "status": e.status, "error": e.error_code}
        for e in events.filter(status__in=[WebhookStatus.ERREUR, WebhookStatus.REJETE], received_at__gte=week)[:20]
    ]
    return {
        "provider": _provider_code(),
        "webhooks_24h": events.filter(received_at__gte=day).count(),
        "webhooks_failed_24h": events.filter(
            received_at__gte=day, status__in=[WebhookStatus.ERREUR, WebhookStatus.REJETE]
        ).count(),
        "webhooks_7d_by_status": by_status,
        "last_webhook_at": last_event,
        "pending_payments": pending.count(),
        "oldest_pending_at": oldest,
        "payouts_with_discrepancy": Payout.objects.filter(status=PayoutStatus.ECART).count(),
        "payouts_to_reconcile": Payout.objects.filter(status=PayoutStatus.RECU).count(),
        "incidents": incidents,
    }


def _provider_code() -> str:
    from django.conf import settings

    return str(settings.DONATIONS_PROVIDER)


def image_get(*, file_id: int | None, user: Any) -> Any:
    """Visuel d'une campagne : un fichier téléversé par la personne elle-même."""
    if file_id is None:
        return None
    from apps.files.models import File

    file_obj = File.objects.filter(pk=file_id, uploaded_by=user).first()
    if file_obj is None:
        raise NotFoundError("Fichier introuvable.")
    return file_obj


def activations_list() -> QuerySet[DonationActivation]:
    return DonationActivation.objects.select_related("node").order_by("node__name")


# --- Clôtures, ajustements, incidents -------------------------------------------------------


def closings_for_parish(*, node: Node) -> QuerySet[MonthClosing]:
    return MonthClosing.objects.filter(node=node).select_related("closed_by__profile").order_by("-month")


def adjustments_for_parish(*, node: Node) -> QuerySet[DonationAdjustment]:
    return (
        DonationAdjustment.objects.filter(node=node)
        .select_related("fund", "donation", "created_by__profile")
        .order_by("-value_date", "-created_at")
    )


def incidents_for_parish(*, node: Node, status: str | None = None) -> QuerySet[PaymentIncident]:
    qs = PaymentIncident.objects.filter(donation__fund__node=node).select_related("donation__fund", "resolved_by__profile")
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-created_at")


def incident_get(*, incident_id: int) -> PaymentIncident:
    incident = PaymentIncident.objects.select_related("donation__fund__node__type").filter(pk=incident_id).first()
    if incident is None:
        raise NotFoundError("Incident introuvable.")
    return incident
