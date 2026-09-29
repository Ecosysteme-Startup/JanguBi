"""Jeu de données de référence (fictif) : Saint-Dominique, septembre 2026 (spec ECRANS-TABLEAU-DE-BORD-DONS §2).

Collecté 1 214 830 = en ligne 356 330 (47 dons) + espèces 858 500 (9 quêtes) ; par type de fonds
259 905 / 674 525 / 236 400 / 44 000 ; semaines, sources, moyens et lieux du §2.3 et §2.4 ; une quête
à confirmer de 64 000 (chapelle, dim. 27, 17 h) ; 58 paiements lancés (47 confirmés, 3 en attente,
4 échoués, 4 expirés). Construit directement en base (dates du passé), à utiliser sous
``freeze_time("2026-09-27 20:00:00")``.

Sert aux tests d'analyse et à produire les exemples de ``docs/API-DONS-ANALYSE.md``.
"""

import datetime
from types import SimpleNamespace
from typing import Any

from django.utils import timezone

from apps.donations import services
from apps.donations.enums import (
    CashCollectionStatus,
    DonationChannel,
    DonationStatus,
    FundDestination,
    FundKind,
    FundStatus,
)
from apps.donations.models import CashCollection, CashDeposit, Donation, DonationActivation, Fund, Payout
from apps.donations.seed_septembre import (  # constantes partagées avec les données de test
    CAMPAIGN_BEFORE,
    CAMPAIGN_DONATIONS,
    CASH,
    FEES_TOTAL,
    ONLINE_CELLS,
    ONLINE_GROUPS,
    PAID_OUT_NET,
    SUNDAYS,
    UTC,
    WEEK_START,
)
from apps.donations.seed_septembre import subset as _subset
from apps.donations.seed_septembre import transport as _transport
from apps.hierarchy.models import PlaceOfWorship
from apps.hierarchy.tests.factories import make_node


def _dt(day: datetime.date, hour: int, minute: int = 0) -> datetime.datetime:
    return datetime.datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def _donation(fund: Fund, amount: int, **fields: Any) -> Donation:
    defaults = {"fee_amount": 0, "charged_amount": amount, "net_amount": amount, "fees_covered": False}
    return Donation.objects.create(reference=services._new_reference(), fund=fund, amount=amount,
                                   **{**defaults, **fields})  # fmt: skip


def build(world: Any) -> SimpleNamespace:
    """Construit le jeu du §2 sur ``world`` (fixture ``world`` des tests dons). Renvoie les objets utiles."""
    sd, dakar = world.sd, world.dakar
    eglise = world.place
    PlaceOfWorship.objects.filter(pk=eglise.pk).update(is_main=True)
    chapelle = PlaceOfWorship.objects.create(node=sd, name="Chapelle de la Cité universitaire", kind="chapelle")
    places = {"eglise": eglise, "chapelle": chapelle}

    common = {"node": sd, "status": FundStatus.OUVERT, "destination": FundDestination.PAROISSE}
    funds = {
        "dom": Fund.objects.create(kind=FundKind.QUETE_DOMINICALE, title="Quête dominicale", **common),
        "camp": Fund.objects.create(kind=FundKind.CAMPAGNE, title="Toiture de la chapelle", goal_amount=4_500_000,
                                    starts_on=datetime.date(2026, 6, 1), ends_on=datetime.date(2026, 12, 31),
                                    place=chapelle, **common),
        "contrib": Fund.objects.create(kind=FundKind.CONTRIBUTION_ANNUELLE, title="Contribution annuelle 2026", **common),
    }  # fmt: skip
    parent = Fund.objects.create(
        node=dakar, kind=FundKind.QUETE_IMPEREE, destination=FundDestination.CURIE, status=FundStatus.OUVERT,
        title="Quête impérée · Grand Séminaire de Brin", starts_on=SUNDAYS[27], remit_by=datetime.date(2026, 10, 4),
        messe_anticipee_incluse=True,
    )  # fmt: skip
    funds["imp"] = Fund.objects.create(
        node=sd, parent=parent, kind=FundKind.QUETE_IMPEREE, destination=FundDestination.CURIE,
        status=FundStatus.OUVERT, title=parent.title, starts_on=parent.starts_on, remit_by=parent.remit_by,
        messe_anticipee_incluse=True,
    )  # fmt: skip

    # Dons en ligne confirmés.
    entries = _transport()
    fees = [max(round(e.amount * 0.02), 1) for e in entries]
    fees[-1] += FEES_TOTAL - sum(fees)
    online: list[Donation] = []
    for n, (e, fee) in enumerate(zip(entries, fees, strict=True)):
        kind, week, _ = ONLINE_CELLS[e.cell]
        source, method, _, _ = ONLINE_GROUPS[e.group]
        day = max(WEEK_START[week], SUNDAYS[week] - datetime.timedelta(days=n % 7))
        if kind == "imp":
            day = SUNDAYS[27] - datetime.timedelta(days=n % 2)
        confirmed = _dt(day, 8 + n % 12, n % 60)
        online.append(_donation(
            funds[kind], e.amount, fee_amount=fee, net_amount=e.amount - fee, fee_is_actual=True,
            channel=DonationChannel.EN_LIGNE, source=source, payment_method=method, status=DonationStatus.CONFIRME,
            confirmed_at=confirmed, status_changed_at=confirmed, value_date=day,
        ))  # fmt: skip
    for d in online:
        assert d.confirmed_at is not None
        Donation.objects.filter(pk=d.pk).update(created_at=d.confirmed_at - datetime.timedelta(seconds=41))
    # Reversement de l'agrégateur du 25 septembre (net 301 480).
    payout = Payout.objects.create(
        provider="fake", external_ref="PAYOUT-2026-09-25", node=dakar, paid_at=_dt(datetime.date(2026, 9, 25), 9),
        gross_amount=0, fee_amount=0, net_amount=PAID_OUT_NET, status="rapproche",
    )  # fmt: skip
    chosen = _subset([d.net_amount for d in online], PAID_OUT_NET)
    Donation.objects.filter(pk__in=[online[i].pk for i in chosen]).update(payout=payout)

    # Paiements non aboutis : 3 en attente (le plus ancien depuis 19 h), 4 échoués, 4 expirés.
    for n, (status, created) in enumerate(
        [(DonationStatus.EN_ATTENTE, _dt(SUNDAYS[27], 1)), (DonationStatus.EN_ATTENTE, _dt(SUNDAYS[27], 11)),
         (DonationStatus.EN_ATTENTE, _dt(SUNDAYS[27], 18))]
        + [(DonationStatus.ECHOUE, _dt(datetime.date(2026, 9, 3 + 5 * i), 10)) for i in range(4)]
        + [(DonationStatus.EXPIRE, _dt(datetime.date(2026, 9, 5 + 5 * i), 21)) for i in range(4)]
    ):  # fmt: skip
        d = _donation(funds["camp"], 5_000 + 1_000 * n, channel=DonationChannel.EN_LIGNE, status=status,
                      source=ONLINE_GROUPS[n % len(ONLINE_GROUPS)][0], status_changed_at=created)  # fmt: skip
        Donation.objects.filter(pk=d.pk).update(created_at=created)

    # Campagne : cumul avant septembre (950 000), pour 57 dons au total.
    before = CAMPAIGN_DONATIONS - sum(1 for d in online if d.fund_id == funds["camp"].pk)
    per_month = [before // 3 + (1 if i < before % 3 else 0) for i in range(3)]
    for (day, total), count in zip(CAMPAIGN_BEFORE, per_month, strict=True):
        base, rest = divmod(total, count)
        for p in range(count):
            amount = base + (rest if p == 0 else 0)
            at = _dt(day, 12)
            d = _donation(funds["camp"], amount, channel=DonationChannel.EN_LIGNE, source="web", payment_method="wave",
                          status=DonationStatus.CONFIRME, confirmed_at=at, status_changed_at=at, value_date=day)  # fmt: skip
            Donation.objects.filter(pk=d.pk).update(created_at=at - datetime.timedelta(minutes=1))

    # Quêtes en espèces validées, puis la quête du dim. 27, 17 h, à confirmer.
    collections = []
    for kind, mass_date, label, where, amount in CASH:
        validated_at = _dt(mass_date + datetime.timedelta(days=1 if mass_date.day == 20 else 0), 20)
        c = CashCollection.objects.create(
            node=sd, fund=funds[kind], place=places[where], mass_date=mass_date, mass_label=label, amount=amount,
            counter_one="Pierre Gomis", counter_two="Thérèse Sagna", status=CashCollectionStatus.VALIDEE,
            entered_by=world.secretaire, validated_by=world.econome, validated_at=validated_at,
        )  # fmt: skip
        collections.append(c)
        _donation(funds[kind], amount, channel=DonationChannel.ESPECES, payment_method="especes", anonymous=True,
                  status=DonationStatus.CONFIRME, confirmed_at=validated_at, status_changed_at=validated_at,
                  value_date=mass_date, place=places[where], cash_collection=c)  # fmt: skip
    deposit = CashDeposit.objects.create(
        node=sd, deposited_on=datetime.date(2026, 9, 22), bank_label="CBAO, compte de la paroisse",
        slip_number="BRD-2026-0412", amount=212_500, declared_by=world.econome,
    )  # fmt: skip
    CashCollection.objects.filter(pk__in=[c.pk for c in collections if c.fund_id == funds["dom"].pk]).update(
        deposit=deposit
    )
    pending_cash = CashCollection.objects.create(
        node=sd, fund=funds["dom"], place=chapelle, mass_date=SUNDAYS[27], mass_label="Messe de 17 h", amount=64_000,
        counter_one="Jean Mendy", counter_two="Rose Diatta", entered_by=world.secretaire,
    )  # fmt: skip
    CashCollection.objects.filter(pk=pending_cash.pk).update(created_at=_dt(SUNDAYS[27], 18, 30))

    # Archidiocèse : cinq paroisses engagées, une seule collecte ouverte.
    for name, code in [("Cathédrale Notre-Dame-des-Victoires", "T-CATH"), ("Notre-Dame des Anges de Ouakam", "T-OUK"),
                       ("Saint-Joseph de Médina", "T-SJM"), ("Sainte-Thérèse de Grand-Dakar", "T-STGD")]:  # fmt: skip
        parish = make_node("paroisse", name, world.tree.doyenne, code=code)
        DonationActivation.objects.create(node=parish, enabled=False)
    return SimpleNamespace(funds=funds, parent=parent, eglise=eglise, chapelle=chapelle, pending_cash=pending_cash,
                           online=online, payout=payout, now=timezone.now())  # fmt: skip
