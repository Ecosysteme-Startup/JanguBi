"""Dons et quêtes : toutes les lectures (ADR-017). Aucune écriture.

Anonymat et agrégats : les sélecteurs publics et diocésains ne renvoient que des totaux ; le
masquage des noms est décidé par l'appelant (capacité ``dons.voir_donateurs``).
"""

import datetime
from typing import Any
from uuid import UUID

from django.db.models import Count, Q, QuerySet, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from apps.core.exceptions import NotFoundError
from apps.donations.enums import (
    CashCollectionStatus,
    DonationChannel,
    DonationStatus,
    FundKind,
    FundStatus,
    PayoutStatus,
    WebhookStatus,
)
from apps.donations.models import (
    CashCollection,
    Donation,
    DonationActivation,
    Fund,
    PaymentAttempt,
    PaymentWebhookEvent,
    Payout,
)
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
    return queryset.select_related("node", "image").annotate(
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
    """Collecté sur le mois (dons confirmés, montant affecté) : par fonds, par moyen, en ligne ou
    espèces, et une série quotidienne (le seul graphique de l'écran)."""
    start, end = _month_bounds(month)
    qs = Donation.objects.filter(
        fund__node=node, status=DonationStatus.CONFIRME, confirmed_at__date__gte=start, confirmed_at__date__lt=end
    )
    totals = qs.aggregate(
        total=_sum("net_amount"),
        online=_sum("net_amount", Q(channel=DonationChannel.EN_LIGNE)),
        cash=_sum("net_amount", Q(channel=DonationChannel.ESPECES)),
        fees=_sum("fee_amount", Q(channel=DonationChannel.EN_LIGNE)),
        count=Count("id"),
    )
    by_fund = qs.values("fund_id", "fund__title", "fund__kind").annotate(total=Sum("net_amount"), count=Count("id"))
    by_method = qs.values("payment_method").annotate(total=Sum("net_amount"), count=Count("id"))
    daily = (
        qs.annotate(day=TruncDate("confirmed_at")).values("day").annotate(total=Sum("net_amount")).order_by("day")
    )
    pending = Donation.objects.filter(
        fund__node=node, status__in=[DonationStatus.INITIE, DonationStatus.EN_ATTENTE]
    ).count()
    cash_to_validate = CashCollection.objects.filter(node=node, status=CashCollectionStatus.SAISIE).count()
    return {
        "month": start,
        **totals,
        "pending_count": pending,
        "cash_to_validate": cash_to_validate,
        "by_fund": [
            {"fund_id": r["fund_id"], "title": r["fund__title"], "kind": r["fund__kind"],
             "total": r["total"], "count": r["count"]}
            for r in by_fund.order_by("-total")
        ],  # fmt: skip
        "by_method": [
            {"method": r["payment_method"], "total": r["total"], "count": r["count"]}
            for r in by_method.order_by("-total")
        ],
        "daily": [{"date": r["day"], "total": r["total"]} for r in daily],
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
        .select_related("fund", "donor__profile", "cash_collection")
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
    donation = Donation.objects.select_related("fund__node__type", "donor__profile").filter(pk=donation_id).first()
    if donation is None:
        raise NotFoundError("Opération introuvable.")
    return donation


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
    """Nom affiché d'un donateur. Un don anonyme ne l'est jamais, même pour ``dons.voir_donateurs``."""
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
    """Par paroisse : en ligne, espèces, nombre de dons. Aucune donnée nominative."""
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
    return [
        {"fund_id": r["id"], "parish_id": r["node_id"], "parish": r["node__name"], "status": r["status"],
         "online": r["online"], "cash": r["cash"], "count": r["count"], "total": r["online"] + r["cash"]}
        for r in rows
    ]  # fmt: skip


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
