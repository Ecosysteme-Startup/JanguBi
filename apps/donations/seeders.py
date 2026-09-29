"""Semeur des dons et quêtes (``seed_realiste``, lot S2) : le cœur des tableaux de bord.

Calendrier réel sur ``--historique`` mois (samedi soir et dimanche selon les horaires de chaque lieu,
grandes fêtes, Popenguine, quêtes impérées), montants log-normaux arrondis aux coupures, moyens de
paiement et canaux réalistes, ~8 % d'échecs, incidents, espèces à deux compteurs, dépôts sous 48 h
(avec des retards), remises à la curie, reversements rapprochés, clôtures mensuelles par le vrai
service, un remboursement et une correction. Le mois de septembre 2026 de Saint-Dominique reproduit
exactement le jeu de la spec (1 214 830 FCFA), partagé avec les tests (``seed_septembre``).

Écriture en masse par ``COPY`` (``apps.core.seeding.bulk``) : aucun signal, aucune tâche.
"""

from __future__ import annotations

import datetime
import itertools
import math
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.seeding import bulk, calendrier, names
from apps.core.seeding.context import DOMAIN, SeedContext
from apps.core.seeding.registry import Check, Phase, Seeder, register
from apps.donations import seed_septembre as sept
from apps.donations.enums import (
    DonationChannel,
    DonationStatus,
    FundDestination,
    FundKind,
    FundStatus,
)
from apps.hierarchy.seeders import staff_of

SEPT_FIRST = datetime.date(2026, 9, 1)
SEPT_LAST_SUNDAY = datetime.date(2026, 9, 27)
PILOT_CAMPAIGN_START = datetime.date(2026, 6, 1)
PILOT_CAMPAIGN_BEFORE_SEPT = 2_463_600  # + 236 400 en septembre = 2 700 000, 60 % de 4 500 000
COUPURES = [500, 1_000, 1_500, 2_000, 2_500, 3_000, 5_000, 7_500, 10_000, 15_000, 20_000, 25_000, 50_000, 100_000]
METHODS = [("wave", 55), ("orange_money", 30), ("carte", 10), ("free_money", 5)]
SOURCES = [("app_android", 48), ("web", 27), ("app_ios", 13), ("qr", 12)]
BANKS = ["CBAO, compte de la paroisse", "SGBS, compte de la paroisse", "Ecobank, compte de la paroisse"]
CAMPAIGNS = [
    ("Réfection du clocher", "Reprise de la maçonnerie et des cloches.", 3_500_000),
    ("Salle paroissiale", "Construction d'une salle pour le catéchisme et les réunions.", 6_000_000),
    ("Sonorisation de l'église", "Nouveaux micros et haut-parleurs pour la nef.", 1_800_000),
    ("Bancs de la chapelle", "Remplacement des bancs abîmés.", 1_200_000),
    ("Panneaux solaires du presbytère", "Autonomie électrique pendant les coupures.", 4_000_000),
]
CLOSED_CAMPAIGN = ("Ventilateurs de la nef", "Achat et pose de douze ventilateurs avant l'hivernage.", 900_000)


def _uuid(rng: Any) -> uuid.UUID:
    return uuid.UUID(int=rng.getrandbits(128), version=4)


def _reference(rng: Any, used: set[str]) -> str:
    while True:
        digits = str(rng.randrange(10**11, 10**12))
        ref = f"{digits[:4]}-{digits[4:8]}-{digits[8:]}"
        if ref not in used:
            used.add(ref)
            return ref


def _coupure(rng: Any, median: float, sigma: float = 0.9) -> int:
    raw = math.exp(rng.gauss(math.log(median), sigma))
    return min(COUPURES, key=lambda c: abs(c - raw))


def _fees(amount: int, covered: bool) -> tuple[int, int, int]:
    fee = math.ceil(amount * settings.DONATIONS_FEE_RATE_BP / 10_000)
    return (fee, amount + fee, amount) if covered else (fee, amount, max(amount - fee, 0))


def _round25(value: float) -> int:
    return max(25, int(round(value / 25.0)) * 25)


class _Donors:
    """Donateurs d'une paroisse, tirés selon leur générosité (poids cumulés calculés une fois)."""

    def __init__(self, users: list[Any], weights: list[float]) -> None:
        self.users = users
        self.cum = list(itertools.accumulate(weights))

    def __bool__(self) -> bool:
        return bool(self.users)

    def pick(self, rng: Any) -> Any:
        return rng.choices(self.users, cum_weights=self.cum)[0]


@dataclass
class ParishPlan:
    node: Any
    main_place: Any
    places: list[Any]
    secretaire: Any
    econome: Any
    cure: Any
    prefix: str
    dom: Any = None
    contrib: dict[int, Any] = field(default_factory=dict)
    camp: Any = None
    camp_closed: Any = None
    imperees: dict[datetime.date, Any] = field(default_factory=dict)
    fideles: list[Any] = field(default_factory=list)
    weight: float = 1.0
    base: float = 40_000.0


@register
class DonsSeeder(Seeder):
    name = "dons"
    module = "dons"
    phase = Phase.DONS
    depends = ("appartenances",)

    # --- Semis ---------------------------------------------------------------------------------------

    def seed(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.donations.models import Donation

        rng = ctx.rng(self.name)
        self.ctx, self.rng = ctx, rng
        self.used_refs = set(Donation.objects.values_list("reference", flat=True))
        from apps.donations.models import DonationActivation

        self.used_prefixes = {p.upper() for p in DonationActivation.objects.values_list("receipt_prefix", flat=True) if p}
        self.diocese = _diocese()
        self.econome_dio = ctx.persona("econome_dio")
        parishes = ctx.parishes()
        self.pilot_id = parishes[0].pk
        self.sept_applies = ctx.start <= SEPT_FIRST and ctx.today >= SEPT_LAST_SUNDAY
        with transaction.atomic():
            plans = [self._plan(p, i) for i, p in enumerate(parishes)]
            self._imperees(plans)
            collections, cash_donations = self._cash(plans)
            online = self._online(plans, target=max(0, ctx.scale.dons - len(cash_donations)))
            sept_counts = self._september(plans[0]) if self.sept_applies else {}
            self._receipts(online)
            self._payouts(online)  # avant l'écriture : le reversement est posé sur les dons en mémoire
            bulk.copy_models(Donation, cash_donations + online)
            self._status_changes(online)
            self._attempts_and_incidents(online)
            self._refund_and_correction(plans, online)
            self._fund_updates(plans)
            closings = self._closings(plans)
        return {
            "fonds": len(ctx.tracked_ids("donations.fund", self.name)),
            "quetes": len(collections),
            "dons_en_ligne": len(online),
            "dons_especes": len(cash_donations),
            "septembre_exact": "oui" if sept_counts else "non",
            "clotures": closings,
        }

    def _plan(self, node: Any, index: int) -> ParishPlan:
        from apps.donations.models import DonationActivation, Fund

        ctx, rng = self.ctx, self.rng
        places = list(node.places.filter(is_active=True).order_by("-is_main", "name"))
        activation = DonationActivation.objects.filter(node=node).first()
        prefix = "".join(w[0] for w in names.slug(node.name.removeprefix("Paroisse ")).split("-") if w)[:4].upper() or "P"
        base, k = prefix[:6], 1
        while prefix in self.used_prefixes:  # les numéros de reçu sont uniques sur toute la plateforme
            k += 1
            prefix = f"{base}{k}"
        if activation is None:
            activation = DonationActivation.objects.create(
                node=node, enabled=True, authorization_ref=f"TEST-ARCH-DAK-{ctx.graine}",
                authorization_date=ctx.start, allocation_key=f"TEST-{node.code[-6:]}", receipt_prefix=prefix or "JB",
                authorization_text="Collecte autorisée par l'Archevêché de Dakar (données de test).",
            )  # fmt: skip
            ctx.track(DonationActivation, [activation.pk])
        self.used_prefixes.add((activation.receipt_prefix or prefix).upper())
        plan = ParishPlan(
            node=node, main_place=places[0] if places else None, places=places,
            secretaire=staff_of(node, "secretaire_paroissial"), econome=staff_of(node, "econome_paroissial"),
            cure=staff_of(node, "cure"), prefix=(activation.receipt_prefix or prefix or "JB").upper(),
            weight=3.0 if index == 0 else max(0.6, 1.6 - 0.05 * index),
            base=rng.uniform(55_000, 95_000) if index == 0 else rng.uniform(25_000, 70_000),
        )  # fmt: skip
        plan.fideles = list(ctx.members(primary_only=True).get(node.pk, []))
        created: list[Any] = []

        def fund(**fields: Any) -> Any:
            f = Fund.objects.create(
                node=node, decided_by=plan.cure, decided_by_office="cure",
                published_at=ctx.aware(fields.get("starts_on") or ctx.start, 9), **fields,
            )  # fmt: skip
            created.append(f.pk)
            return f

        is_pilot = node.pk == self.pilot_id
        plan.dom = fund(kind=FundKind.QUETE_DOMINICALE, title="Quête dominicale", status=FundStatus.OUVERT,
                        description="Vie de la paroisse, entretien des lieux et charges courantes.",
                        starts_on=ctx.start)  # fmt: skip
        for year in range(ctx.start.year, ctx.today.year + 1):
            existing = Fund.objects.filter(node=node, kind=FundKind.CONTRIBUTION_ANNUELLE, title__endswith=str(year))
            demo = existing.exclude(pk__in=created).first() if is_pilot else None
            plan.contrib[year] = demo or fund(
                kind=FundKind.CONTRIBUTION_ANNUELLE, title=f"Contribution annuelle {year}",
                description="Participation des fidèles à la vie de l'Église.",
                starts_on=datetime.date(year, 1, 1), ends_on=datetime.date(year, 12, 31),
                status=FundStatus.OUVERT if year == ctx.today.year else FundStatus.CLOS,
            )  # fmt: skip
            if plan.contrib[year].status == FundStatus.CLOS and not plan.contrib[year].closed_at:
                Fund.objects.filter(pk=plan.contrib[year].pk).update(closed_at=ctx.aware(datetime.date(year, 12, 31), 23))
        demo_camp = (
            Fund.objects.filter(node=node, kind=FundKind.CAMPAGNE, title__startswith="Toiture").first() if is_pilot else None
        )
        if demo_camp is not None:
            # Jeu de septembre : la campagne court depuis juin (950 000 avant septembre dans la spec).
            if demo_camp.starts_on and demo_camp.starts_on > PILOT_CAMPAIGN_START:
                Fund.objects.filter(pk=demo_camp.pk).update(starts_on=PILOT_CAMPAIGN_START)
                demo_camp.starts_on = PILOT_CAMPAIGN_START
                ctx.note("Campagne « Toiture » de seed_demo : début avancé au 1er juin 2026 (jeu de la spec).")
            place = next((p for p in places if not p.is_main), None)
            if place is not None and demo_camp.place_id is None:
                Fund.objects.filter(pk=demo_camp.pk).update(place=place)
            plan.camp = demo_camp
        else:
            title, description, goal = CAMPAIGNS[index % len(CAMPAIGNS)]
            start = max(ctx.start, ctx.today - datetime.timedelta(days=rng.randint(90, 260)))
            plan.camp = fund(kind=FundKind.CAMPAGNE, title=title, description=description, goal_amount=goal,
                             starts_on=start, ends_on=ctx.today + datetime.timedelta(days=rng.randint(60, 200)),
                             status=FundStatus.OUVERT)  # fmt: skip
        title, description, goal = CLOSED_CAMPAIGN
        c_start = ctx.start + datetime.timedelta(days=rng.randint(10, 40))
        plan.camp_closed = fund(kind=FundKind.CAMPAGNE, title=title, description=description, goal_amount=goal,
                                starts_on=c_start, ends_on=c_start + datetime.timedelta(days=75), status=FundStatus.CLOS)  # fmt: skip
        Fund.objects.filter(pk=plan.camp_closed.pk).update(closed_at=ctx.aware(c_start + datetime.timedelta(days=75), 18))
        ctx.track(Fund, created)
        return plan

    def _imperees(self, plans: list[ParishPlan]) -> None:
        from apps.donations.models import Fund

        ctx = self.ctx
        created: list[Any] = []
        for imp in calendrier.imperees(ctx.start, ctx.today):
            closed = imp.day + datetime.timedelta(days=7) < ctx.today
            common = dict(
                kind=FundKind.QUETE_IMPEREE, destination=FundDestination.CURIE, title=imp.title,
                description=imp.description, starts_on=imp.day, ends_on=imp.day + datetime.timedelta(days=7),
                remit_by=imp.day + datetime.timedelta(days=14), messe_anticipee_incluse=imp.anticipee,
                status=FundStatus.CLOS if closed else FundStatus.OUVERT, authorization_ref=f"TEST-ARCH-DAK-{ctx.graine}",
                published_at=ctx.aware(imp.day - datetime.timedelta(days=10), 9),
                closed_at=ctx.aware(imp.day + datetime.timedelta(days=7), 20) if closed else None,
            )  # fmt: skip
            parent = Fund.objects.create(node=self.diocese, decided_by=self.econome_dio,
                                         decided_by_office="econome_diocesain", **common)  # fmt: skip
            created.append(parent.pk)
            for plan in plans:
                child = Fund.objects.create(node=plan.node, parent=parent, **common)
                created.append(child.pk)
                plan.imperees[imp.day] = child
        # Quête impérée de Brin (seed_demo, 27 septembre) : messe anticipée incluse (jeu de la spec),
        # déclinée aussi sur les autres paroisses peuplées.
        brin = Fund.objects.filter(node=self.diocese, kind=FundKind.QUETE_IMPEREE, title__contains="Brin").first()
        if brin is not None and brin.starts_on and ctx.start <= brin.starts_on <= ctx.today:
            Fund.objects.filter(Q(pk=brin.pk) | Q(parent=brin)).update(messe_anticipee_incluse=True)
            for plan in plans:
                existing = Fund.objects.filter(parent=brin, node=plan.node).first()
                if existing is not None:
                    child = existing
                else:
                    child = Fund.objects.create(
                        node=plan.node, parent=brin, kind=FundKind.QUETE_IMPEREE, destination=FundDestination.CURIE,
                        title=brin.title, description=brin.description, starts_on=brin.starts_on, ends_on=brin.ends_on,
                        remit_by=brin.remit_by, messe_anticipee_incluse=True, status=brin.status,
                        published_at=brin.published_at,
                    )  # fmt: skip
                    created.append(child.pk)
                plan.imperees[brin.starts_on] = child
        ctx.track(Fund, created)

    # --- Espèces -------------------------------------------------------------------------------------

    def _masses(self, plan: ParishPlan, day: datetime.date) -> list[tuple[Any, datetime.time, str]]:
        """Messes quêtées ce jour : samedi soir, dimanche, ou solennité (horaire du dimanche)."""
        from apps.hierarchy.models import MassSchedule

        if not hasattr(plan, "_schedules"):
            plan._schedules = list(  # type: ignore[attr-defined]
                MassSchedule.objects.filter(place__node=plan.node, kind="messe", place__is_active=True)
                .select_related("place")
                .order_by("start_time")
            )
        feast = calendrier.is_feast_day(day)
        wd = day.weekday()
        out = []
        for s in plan._schedules:  # type: ignore[attr-defined]
            if wd == 6 or (feast and wd != 5):
                if s.weekday == 6:
                    out.append((s.place, s.start_time, ""))
            elif wd == 5 and s.weekday == 5 and s.start_time >= datetime.time(17, 0):
                out.append((s.place, s.start_time, "anticipée "))
        return out

    def _cash(self, plans: list[ParishPlan]) -> tuple[list[Any], list[Any]]:
        from apps.donations.models import CashCollection, CashDeposit, CuriaRemittance, Donation

        ctx, rng = self.ctx, self.rng
        collections: list[Any] = []
        donations: list[Any] = []
        deposits_by: dict[tuple[Any, datetime.date], list[Any]] = defaultdict(list)
        remit_by: dict[tuple[Any, Any], list[Any]] = defaultdict(list)
        day = ctx.start
        while day <= ctx.today:
            feast = calendrier.is_feast_day(day)
            for plan in plans:
                if plan.node.pk == self.pilot_id and self.sept_applies and day >= SEPT_FIRST:
                    continue
                for place, start, label in self._masses(plan, day):
                    mult = feast[1] if feast else 1.0
                    if day.month in (7, 8, 9):
                        mult *= 0.9  # hivernage, vacances
                    if day.day >= 25 or day.day <= 3:
                        mult *= 1.12  # fin de mois
                    hour_factor = {7: 0.7, 8: 0.6, 9: 1.0, 10: 0.7, 11: 1.3, 17: 0.6, 18: 0.8}.get(start.hour, 0.8)
                    place_factor = 1.0 if place.is_main else 0.5
                    amount = _round25(plan.base * mult * hour_factor * place_factor * math.exp(rng.gauss(0, 0.18)))
                    if day.weekday() == 5:
                        imp = plan.imperees.get(day + datetime.timedelta(days=1))
                        is_imp = imp is not None and imp.messe_anticipee_incluse
                    else:
                        imp = plan.imperees.get(day)
                        is_imp = imp is not None
                    fund = imp if is_imp else plan.dom
                    hh = f"{start.hour} h" + (f" {start.minute:02d}" if start.minute else "")
                    mass_label = f"Messe {label}de {hh}"
                    recent = (ctx.today - day).days <= 2
                    status = "saisie" if recent and rng.random() < 0.5 else "validee"
                    validated_at = ctx.aware(day + datetime.timedelta(days=rng.choice([0, 1, 1, 2])), 20, rng.randint(0, 59))
                    c = CashCollection(
                        node=plan.node, fund=fund, place=place, mass_date=day, mass_label=mass_label, amount=amount,
                        counter_one=" ".join(names.person(rng)[:2]), counter_two=" ".join(names.person(rng)[:2]),
                        status=status, entered_by=plan.secretaire,
                        validated_by=plan.econome if status == "validee" else None,
                        validated_at=validated_at if status == "validee" else None,
                        created_at=ctx.aware(day, min(start.hour + 2, 23), rng.randint(0, 59)),
                    )  # fmt: skip
                    if status == "validee" and rng.random() < 0.01:
                        # Saisie rejetée (erreur de comptage), ressaisie juste après.
                        rejected = CashCollection(
                            node=plan.node, fund=fund, place=place, mass_date=day, mass_label=mass_label,
                            amount=amount + 1_000, counter_one=c.counter_one, counter_two=c.counter_two,
                            status="rejetee", entered_by=plan.secretaire,
                            rejection_reason="Le total ne correspond pas au bordereau de comptage.",
                            created_at=c.created_at,
                        )  # fmt: skip
                        collections.append(rejected)
                    collections.append(c)
            day += datetime.timedelta(days=1)
        CashCollection.objects.bulk_create(collections, batch_size=5000)
        tracked = [c.pk for c in collections]
        self.ctx.track(CashCollection, tracked)

        for c in collections:
            if c.status != "validee":
                continue
            donations.append(
                Donation(
                    id=_uuid(rng), reference=_reference(rng, self.used_refs), fund=c.fund, amount=c.amount,
                    fee_amount=0, charged_amount=c.amount, net_amount=c.amount, anonymous=True,
                    channel=DonationChannel.ESPECES, payment_method="especes", source=None, place=c.place,
                    value_date=c.mass_date, status=DonationStatus.CONFIRME, status_changed_at=c.validated_at,
                    confirmed_at=c.validated_at, cash_collection=c, created_at=c.validated_at,
                )  # fmt: skip
            )
            if c.fund.kind == FundKind.QUETE_IMPEREE:
                remit_by[(c.node_id, c.fund_id)].append(c)
            else:
                week = c.mass_date - datetime.timedelta(days=(c.mass_date.weekday() + 2) % 7)  # samedi → vendredi
                deposits_by[(c.node_id, week)].append(c)

        plan_of = {p.node.pk: p for p in plans}
        deposits: list[Any] = []
        seq: dict[Any, int] = defaultdict(int)
        links: list[tuple[Any, list[Any]]] = []
        for (node_id, week), items in sorted(deposits_by.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
            last = max(i.mass_date for i in items)
            delay = rng.choice([1, 1, 2, 2, 2]) if rng.random() > 0.1 else rng.randint(4, 9)
            deposited_on = last + datetime.timedelta(days=delay)
            if deposited_on > ctx.today:
                continue  # espèces pas encore déposées
            plan = plan_of[node_id]
            seq[(node_id, deposited_on.year)] += 1
            d = CashDeposit(
                node_id=node_id, deposited_on=deposited_on, bank_label=BANKS[sum(map(ord, plan.prefix)) % len(BANKS)],
                slip_number=f"BRD-{deposited_on.year}-T{seq[(node_id, deposited_on.year)]:04d}",
                amount=sum(i.amount for i in items), declared_by=plan.econome,
                note="Dépôt en retard : banque fermée (jour férié)." if delay > 3 else "",
                created_at=ctx.aware(deposited_on, 11),
            )  # fmt: skip
            deposits.append(d)
            links.append((d, items))
        CashDeposit.objects.bulk_create(deposits, batch_size=2000)
        self.ctx.track(CashDeposit, [d.pk for d in deposits])
        for d, items in links:
            CashCollection.objects.filter(pk__in=[i.pk for i in items]).update(deposit=d)

        remittances: list[Any] = []
        for (node_id, _fund_id), items in remit_by.items():
            fund = items[0].fund
            plan = plan_of[node_id]
            remitted_on = max(i.mass_date for i in items) + datetime.timedelta(days=rng.randint(3, 10))
            if remitted_on > ctx.today:
                continue  # à remettre avant l'échéance : reste « à traiter »
            confirmed = rng.random() < 0.9
            remittances.append(
                CuriaRemittance(
                    fund=fund, node_id=node_id, amount=sum(i.amount for i in items), remitted_on=remitted_on,
                    mode=rng.choice(["especes", "especes", "virement", "compensation"]),
                    reference=f"CURIE-{remitted_on:%Y%m%d}-{plan.prefix}",
                    status="confirmee" if confirmed else "declaree", declared_by=plan.econome,
                    confirmed_by=self.econome_dio if confirmed else None,
                    confirmed_at=ctx.aware(remitted_on + datetime.timedelta(days=2), 10) if confirmed else None,
                    created_at=ctx.aware(remitted_on, 10),
                )  # fmt: skip
            )
        CuriaRemittance.objects.bulk_create(remittances)
        self.ctx.track(CuriaRemittance, [r.pk for r in remittances])
        return collections, donations

    # --- En ligne ------------------------------------------------------------------------------------

    def _funds_on(self, plan: ParishPlan, day: datetime.date) -> list[tuple[Any, float, float]]:
        """(fonds, poids, montant médian) ouverts ce jour-là."""
        out: list[tuple[Any, float, float]] = [(plan.dom, 35, 2_000)]
        contrib = plan.contrib.get(day.year)
        if contrib is not None:
            out.append((contrib, 20 if day.month in (1, 2, 3, 11, 12) else 10, 10_000))
        for camp, w in ((plan.camp, 30), (plan.camp_closed, 25)):
            if camp is not None and camp.starts_on and camp.starts_on <= day <= (camp.ends_on or day):
                out.append((camp, w, 5_000))
        for start, imp in plan.imperees.items():
            if start - datetime.timedelta(days=1) <= day <= start + datetime.timedelta(days=7):
                out.append((imp, 45, 2_000))
        return out

    def _online(self, plans: list[ParishPlan], target: int) -> list[Any]:

        ctx, rng = self.ctx, self.rng
        days: list[tuple[ParishPlan, datetime.date]] = []
        weights: list[float] = []
        span = max(1, (ctx.today - ctx.start).days)
        day = ctx.start
        while day <= ctx.today:
            feast = calendrier.is_feast_day(day)
            dow = {6: 3.0, 5: 1.5, 4: 1.2}.get(day.weekday(), 1.0)
            trend = 0.55 + 0.45 * (day - ctx.start).days / span  # adoption croissante sur l'année
            for plan in plans:
                if plan.node.pk == self.pilot_id and self.sept_applies and day >= SEPT_FIRST:
                    continue
                w = plan.weight * dow * trend * (feast[1] if feast else 1.0)
                if any(start - datetime.timedelta(days=1) <= day <= start for start in plan.imperees):
                    w *= 1.4
                days.append((plan, day))
                weights.append(w)
            day += datetime.timedelta(days=1)
        if not days or target <= 0:
            return []
        # Donateurs : ~45 % des fidèles donnent en ligne, les fidèles réguliers plus souvent.
        generosity: dict[Any, _Donors] = {}
        for plan in plans:
            donors = [u for u in plan.fideles if rng.random() < 0.45]
            generosity[plan.node.pk] = _Donors(donors, [rng.paretovariate(1.6) for _ in donors])
        picks = rng.choices(range(len(days)), weights, k=target)
        out: list[Any] = []
        for n, idx in enumerate(picks):
            plan, day = days[idx]
            funds = self._funds_on(plan, day)
            fund, _, median = rng.choices(funds, [f[1] for f in funds])[0]
            out.append(self._online_donation(plan, day, fund, median, n, generosity[plan.node.pk]))
        # Campagne de la pilote : 2 700 000 au total (60 %), dont 236 400 en septembre.
        pilot = plans[0]
        if self.sept_applies and pilot.camp is not None and pilot.camp.starts_on == PILOT_CAMPAIGN_START:
            out = self._pilot_campaign_topup(pilot, out, generosity[pilot.node.pk])
        return out

    def _online_donation(
        self, plan: ParishPlan, day: datetime.date, fund: Any, median: float, n: int, donors: _Donors
    ) -> Any:
        from apps.donations.models import Donation

        ctx, rng = self.ctx, self.rng
        amount = _coupure(rng, median)
        if rng.random() < 0.005:
            amount = rng.choice([150_000, 200_000, 250_000, 500_000, 1_000_000])  # rares gros dons
        covered = rng.random() < 0.25
        fee, charged, net = _fees(amount, covered)
        hour = rng.choices([7, 8, 9, 10, 11, 12, 13, 14, 16, 18, 19, 20, 21, 22],
                           [2, 4, 6, 6, 7, 5, 4, 3, 3, 4, 5, 6, 5, 3])[0]  # fmt: skip
        at = ctx.aware(day, hour, rng.randint(0, 59), rng.randint(0, 59))
        if at > ctx.now:
            at = ctx.now - datetime.timedelta(minutes=rng.randint(5, 600))
            day = timezone.localdate(at)
        r = rng.random()
        recent = (ctx.now - at).total_seconds() < 36 * 3600
        if r < 0.045:
            status = DonationStatus.ECHOUE
        elif r < 0.08:
            status = DonationStatus.EN_ATTENTE if recent and rng.random() < 0.5 else DonationStatus.EXPIRE
        else:
            status = DonationStatus.CONFIRME
        source = rng.choices([s for s, _ in SOURCES], [w for _, w in SOURCES])[0]
        donor = None
        donor_email = ""
        if donors and rng.random() < 0.88:
            donor = donors.pick(rng)
        elif (ctx.today - day).days < 90:
            donor_email = f"donateur.sans.compte.{n}@{DOMAIN}"
        place_id = fund.place_id or (plan.main_place.pk if source == "qr" and plan.main_place else None)
        confirmed = status == DonationStatus.CONFIRME
        changed = at if status != DonationStatus.EXPIRE else at + datetime.timedelta(hours=1)
        return Donation(
            id=_uuid(rng), reference=_reference(rng, self.used_refs), fund=fund, amount=amount, fees_covered=covered,
            fee_amount=fee, charged_amount=charged, net_amount=net, anonymous=rng.random() < 0.15,
            donor_id=donor, donor_email=donor_email, channel=DonationChannel.EN_LIGNE,
            payment_method=rng.choices([m for m, _ in METHODS], [w for _, w in METHODS])[0] if confirmed else "inconnu",
            source=source, place_id=place_id, value_date=day if confirmed else None, fee_is_actual=confirmed,
            returned_at=at + datetime.timedelta(seconds=rng.randint(20, 200)) if confirmed and rng.random() < 0.8 else None,
            status=status, status_changed_at=changed, confirmed_at=at if confirmed else None,
            created_at=at - datetime.timedelta(seconds=rng.randint(25, 400)),
            receipt_email_sent_at=at + datetime.timedelta(minutes=1) if confirmed and (donor or donor_email) else None,
        )  # fmt: skip

    def _pilot_campaign_topup(self, pilot: ParishPlan, out: list[Any], donors: _Donors) -> list[Any]:
        rng = self.rng

        def is_camp(d: Any) -> bool:
            return d.fund_id == pilot.camp.pk and d.status == DonationStatus.CONFIRME

        # Un seul passage : on garde les dons de la campagne tant que le cumul reste sous la cible.
        total, dropped = 0, set()
        for d in out:
            if is_camp(d):
                if total + d.amount > PILOT_CAMPAIGN_BEFORE_SEPT:
                    dropped.add(d.pk)
                else:
                    total += d.amount
        if dropped:
            out = [d for d in out if d.pk not in dropped]
        n = len(out)
        while total < PILOT_CAMPAIGN_BEFORE_SEPT:
            day = PILOT_CAMPAIGN_START + datetime.timedelta(days=rng.randint(0, 91))
            d = self._online_donation(pilot, day, pilot.camp, 10_000, n, donors)
            d.status, d.confirmed_at = DonationStatus.CONFIRME, d.status_changed_at
            d.value_date = timezone.localdate(d.confirmed_at)
            d.payment_method = d.payment_method if d.payment_method != "inconnu" else "wave"
            rest = PILOT_CAMPAIGN_BEFORE_SEPT - total
            if rest < 20_000:
                d.amount = rest
            d.fee_amount, d.charged_amount, d.net_amount = _fees(d.amount, d.fees_covered)
            out.append(d)
            total += d.amount
            n += 1
        return out

    # --- Septembre exact (spec) ----------------------------------------------------------------------

    def _september(self, pilot: ParishPlan) -> dict[str, int]:
        """Jeu de la spec §2 sur Saint-Dominique, construit comme ``tests/dataset_septembre.build``."""
        from apps.donations.models import CashCollection, CashDeposit, Donation, Payout

        ctx, rng = self.ctx, self.rng
        brin = pilot.imperees.get(sept.SUNDAYS[27])
        funds = {"dom": pilot.dom, "imp": brin, "camp": pilot.camp, "contrib": pilot.contrib.get(2026)}
        if any(f is None for f in funds.values()) or pilot.main_place is None:
            ctx.note("Jeu de septembre non construit : fonds de seed_demo absents.")
            return {}
        chapelle = next((p for p in pilot.places if not p.is_main), pilot.main_place)
        places = {"eglise": pilot.main_place, "chapelle": chapelle}
        tz = timezone.get_current_timezone()

        def dt(day: datetime.date, hour: int, minute: int = 0) -> datetime.datetime:
            return datetime.datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)

        entries = sept.transport()
        fees = [max(round(e.amount * 0.02), 1) for e in entries]
        fees[-1] += sept.FEES_TOTAL - sum(fees)
        online: list[Any] = []
        donors = pilot.fideles or [None]
        for n, (e, fee) in enumerate(zip(entries, fees, strict=True)):
            kind, week, _ = sept.ONLINE_CELLS[e.cell]
            source, method, _, _ = sept.ONLINE_GROUPS[e.group]
            day = max(sept.WEEK_START[week], sept.SUNDAYS[week] - datetime.timedelta(days=n % 7))
            if kind == "imp":
                day = sept.SUNDAYS[27] - datetime.timedelta(days=n % 2)
            confirmed = dt(day, 8 + n % 12, n % 60)
            online.append(Donation(
                id=_uuid(rng), reference=_reference(rng, self.used_refs), fund=funds[kind], amount=e.amount,
                fee_amount=fee, charged_amount=e.amount, net_amount=e.amount - fee, fee_is_actual=True,
                channel=DonationChannel.EN_LIGNE, source=source, payment_method=method, status=DonationStatus.CONFIRME,
                confirmed_at=confirmed, status_changed_at=confirmed, value_date=day,
                created_at=confirmed - datetime.timedelta(seconds=41), donor_id=donors[n % len(donors)],
                anonymous=n % 7 == 0, place_id=funds[kind].place_id,
            ))  # fmt: skip
        self._sept_online = online
        payout = Payout.objects.create(
            provider="fake", external_ref=f"TEST-PAYOUT-2026-09-25-{pilot.prefix}", node=self.diocese,
            paid_at=dt(datetime.date(2026, 9, 25), 9), gross_amount=0, fee_amount=0, net_amount=sept.PAID_OUT_NET,
            status="rapproche", reconciled_at=dt(datetime.date(2026, 9, 25), 10),
        )  # fmt: skip
        ctx.track(Payout, [payout.pk])
        chosen = sept.subset([d.net_amount for d in online], sept.PAID_OUT_NET)
        for i in chosen:
            online[i].payout = payout
        pending = []
        for n, (status, created) in enumerate(
            [(DonationStatus.EN_ATTENTE, dt(sept.SUNDAYS[27], 1)), (DonationStatus.EN_ATTENTE, dt(sept.SUNDAYS[27], 11)),
             (DonationStatus.EN_ATTENTE, dt(sept.SUNDAYS[27], 18))]
            + [(DonationStatus.ECHOUE, dt(datetime.date(2026, 9, 3 + 5 * i), 10)) for i in range(4)]
            + [(DonationStatus.EXPIRE, dt(datetime.date(2026, 9, 5 + 5 * i), 21)) for i in range(4)]
        ):  # fmt: skip
            amount = 5_000 + 1_000 * n
            pending.append(Donation(
                id=_uuid(rng), reference=_reference(rng, self.used_refs), fund=funds["camp"], amount=amount,
                charged_amount=amount, net_amount=amount, channel=DonationChannel.EN_LIGNE, status=status,
                source=sept.ONLINE_GROUPS[n % len(sept.ONLINE_GROUPS)][0], status_changed_at=created, created_at=created,
            ))  # fmt: skip
        cash_donations, collections = [], []
        for kind, mass_date, label, where, amount in sept.CASH:
            validated_at = dt(mass_date + datetime.timedelta(days=1 if mass_date.day == 20 else 0), 20)
            c = CashCollection.objects.create(
                node=pilot.node, fund=funds[kind], place=places[where], mass_date=mass_date, mass_label=label,
                amount=amount, counter_one="Pierre Gomis", counter_two="Thérèse Sagna", status="validee",
                entered_by=pilot.secretaire, validated_by=pilot.econome, validated_at=validated_at,
                created_at=dt(mass_date, 13),
            )  # fmt: skip
            collections.append(c)
            cash_donations.append(Donation(
                id=_uuid(rng), reference=_reference(rng, self.used_refs), fund=funds[kind], amount=amount,
                charged_amount=amount, net_amount=amount, channel=DonationChannel.ESPECES, payment_method="especes",
                anonymous=True, status=DonationStatus.CONFIRME, confirmed_at=validated_at, status_changed_at=validated_at,
                value_date=mass_date, place=places[where], cash_collection=c, created_at=validated_at,
            ))  # fmt: skip
        deposit = CashDeposit.objects.create(
            node=pilot.node, deposited_on=datetime.date(2026, 9, 22), bank_label="CBAO, compte de la paroisse",
            slip_number="BRD-2026-0412", amount=212_500, declared_by=pilot.econome,
        )  # fmt: skip
        CashCollection.objects.filter(pk__in=[c.pk for c in collections if c.fund_id == funds["dom"].pk]).update(
            deposit=deposit
        )
        pending_cash = CashCollection.objects.create(
            node=pilot.node, fund=funds["dom"], place=chapelle, mass_date=sept.SUNDAYS[27], mass_label="Messe de 17 h",
            amount=64_000, counter_one="Jean Mendy", counter_two="Rose Diatta", entered_by=pilot.secretaire,
            created_at=dt(sept.SUNDAYS[27], 18, 30),
        )  # fmt: skip
        ctx.track(CashCollection, [c.pk for c in collections] + [pending_cash.pk])
        ctx.track(CashDeposit, [deposit.pk])
        self._sept_extra = online + pending + cash_donations
        return {"en_ligne": len(online), "quetes": len(collections)}

    # --- Reçus, journal, tentatives, reversements ------------------------------------------------------

    def _receipts(self, online: list[Any]) -> None:
        from apps.donations.models import Donation, ReceiptSequence

        extra = getattr(self, "_sept_extra", [])
        online.extend(extra)
        prefix_of = {}
        for plan_fund in {d.fund_id: d.fund for d in online}.values():
            node = plan_fund.node
            prefix_of[plan_fund.pk] = node
        by_key: dict[tuple[Any, int], list[Any]] = defaultdict(list)
        for d in online:
            if d.channel == DonationChannel.EN_LIGNE and d.status == DonationStatus.CONFIRME:
                by_key[(prefix_of[d.fund_id].pk, d.confirmed_at.year)].append(d)
        created = []
        from apps.donations.models import DonationActivation

        prefixes = dict(DonationActivation.objects.values_list("node_id", "receipt_prefix"))
        for (node_id, year), items in by_key.items():
            items.sort(key=lambda d: d.confirmed_at)
            seq, was_created = ReceiptSequence.objects.get_or_create(node_id=node_id, year=year)
            if was_created:
                created.append(seq.pk)
            prefix = (prefixes.get(node_id) or "JB").upper()
            for d in items:
                seq.last_number += 1
                d.receipt_number = f"{prefix}-{year}-{seq.last_number:05d}"
            seq.save(update_fields=["last_number"])
        self.ctx.track(ReceiptSequence, created)
        # Dons à fonds non tracés (fonds de seed_demo) : tracés un par un pour --reset.
        tracked_funds = set(self.ctx.tracked_ids("donations.fund"))
        self.ctx.track(Donation, [d.pk for d in online if str(d.fund_id) not in tracked_funds])

    def _status_changes(self, online: list[Any]) -> None:
        from apps.donations.models import DonationStatusChange

        def rows() -> Any:
            for d in online:
                if d.channel != DonationChannel.EN_LIGNE:
                    continue
                if d.status == DonationStatus.ECHOUE:
                    path = [("initie", "echoue", "webhook")]
                elif d.status == DonationStatus.EXPIRE:
                    path = [("initie", "en_attente", "checkout"), ("en_attente", "expire", "reconciliation")]
                elif d.status == DonationStatus.EN_ATTENTE:
                    path = [("initie", "en_attente", "checkout")]
                else:
                    path = [("initie", "en_attente", "checkout"), ("en_attente", "confirme", "webhook")]
                for i, (a, b, src) in enumerate(path):
                    at = d.created_at if i == 0 else (d.status_changed_at or d.created_at)
                    yield [d.pk, a, b, src, None, "", at]

        bulk.copy_rows(
            DonationStatusChange._meta.db_table,
            ["donation_id", "from_status", "to_status", "source", "actor_id", "note", "at"],
            rows(),
        )

    def _attempts_and_incidents(self, online: list[Any]) -> None:
        from apps.donations.models import PaymentAttempt, PaymentIncident

        rng = self.rng
        attempts = []
        failed = [d for d in online if d.status in (DonationStatus.ECHOUE, DonationStatus.EXPIRE, DonationStatus.EN_ATTENTE)]
        status_of = {"echoue": "echoue", "expire": "expire", "en_attente": "en_attente"}
        for d in failed:
            attempts.append(
                PaymentAttempt(
                    donation_id=d.pk, provider="fake", external_ref=f"test_{d.reference}",
                    idempotency_key=f"test-{d.pk}", checkout_url=f"https://paiement.exemple.test/checkout/{d.reference}",
                    status=status_of[d.status], expires_at=d.created_at + datetime.timedelta(hours=1),
                    created_at=d.created_at,
                )  # fmt: skip
            )
        PaymentAttempt.objects.bulk_create(attempts, batch_size=2000)
        pilot_sept = {d.pk for d in getattr(self, "_sept_extra", [])}
        candidates = [a for a, d in zip(attempts, failed, strict=True) if d.status == DonationStatus.ECHOUE and d.pk not in pilot_sept]
        incidents = []
        for i, a in enumerate(candidates[:3]):
            kind = "late_payment" if i != 1 else "amount_mismatch"
            resolved = i == 2
            incidents.append(
                PaymentIncident(
                    attempt=a, donation_id=a.donation_id, kind=kind, status="resolu" if resolved else "ouvert",
                    reported_amount=None if kind == "late_payment" else 4_900,
                    resolution="sans_suite" if resolved else "", note="Vérifié chez l'agrégateur." if resolved else "",
                    resolved_at=self.ctx.now - datetime.timedelta(days=rng.randint(1, 20)) if resolved else None,
                )  # fmt: skip
            )
        PaymentIncident.objects.bulk_create(incidents)

    def _payouts(self, online: list[Any]) -> None:
        from apps.donations.models import Payout

        ctx = self.ctx
        sept_ids = {x.pk for x in getattr(self, "_sept_online", [])}
        confirmed = [
            d for d in online
            if d.channel == DonationChannel.EN_LIGNE and d.status == DonationStatus.CONFIRME and d.payout_id is None
            and d.pk not in sept_ids
        ]  # fmt: skip
        by_friday: dict[datetime.date, list[Any]] = defaultdict(list)
        for d in confirmed:
            day = timezone.localdate(d.confirmed_at)
            friday = day + datetime.timedelta(days=(4 - day.weekday()) % 7 + 7)  # vendredi de la semaine suivante
            if friday <= ctx.today:
                by_friday[friday].append(d)
        payouts, links = [], []
        for i, (friday, items) in enumerate(sorted(by_friday.items())):
            gross = sum(d.charged_amount for d in items)
            net = sum(d.net_amount for d in items)
            ecart = i == len(by_friday) // 2
            p = Payout(
                provider="fake", external_ref=f"TEST-PAYOUT-{friday:%Y-%m-%d}", node=self.diocese,
                paid_at=ctx.aware(friday, 9), gross_amount=gross, fee_amount=gross - net, net_amount=net - (500 if ecart else 0),
                status="ecart" if ecart else "rapproche", discrepancy_amount=-500 if ecart else 0,
                unmatched_count=1 if ecart else 0, reconciled_at=ctx.aware(friday, 11),
            )  # fmt: skip
            payouts.append(p)
            links.append((p, items))
        Payout.objects.bulk_create(payouts)
        ctx.track(Payout, [p.pk for p in payouts])
        for p, items in links:
            for d in items:
                d.payout = p

    def _refund_and_correction(self, plans: list[ParishPlan], online: list[Any]) -> None:
        from apps.donations.models import Donation, DonationAdjustment, DonationStatusChange

        ctx = self.ctx
        others = [p for p in plans if p.node.pk != self.pilot_id]
        if not others:
            return
        created = []
        month_ago = ctx.today.replace(day=1) - datetime.timedelta(days=20)
        target = next(
            (d for d in online if d.status == DonationStatus.CONFIRME and d.channel == DonationChannel.EN_LIGNE
             and d.fund.node_id == others[0].node.pk and d.value_date and d.value_date < month_ago - datetime.timedelta(days=30)),
            None,
        )  # fmt: skip
        if target is not None:
            Donation.objects.filter(pk=target.pk).update(status=DonationStatus.REMBOURSE, status_changed_at=ctx.aware(month_ago, 10))
            DonationStatusChange.objects.create(donation_id=target.pk, from_status="confirme", to_status="rembourse",
                                                source="staff", actor=others[0].econome, note="Double paiement du donateur.")  # fmt: skip
            created.append(DonationAdjustment.objects.create(
                node=others[0].node, fund=target.fund, donation_id=target.pk, kind="remboursement", channel="en_ligne",
                source=target.source, payment_method=target.payment_method, place=target.place,
                amount=-target.amount, net_amount=-target.net_amount, value_date=month_ago,
                reason="Double paiement du donateur, remboursé chez l'agrégateur.", created_by=others[0].econome,
            ).pk)  # fmt: skip
        created.append(DonationAdjustment.objects.create(
            node=others[-1].node, fund=others[-1].dom, kind="correction", channel="especes", amount=2_500, net_amount=2_500,
            value_date=ctx.today, reason="Quête du mois dernier : un billet compté deux fois au lieu d'une (écart corrigé).",
            created_by=others[-1].econome,
        ).pk)  # fmt: skip
        ctx.track(DonationAdjustment, created)

    def _fund_updates(self, plans: list[ParishPlan]) -> None:
        from apps.donations.models import FundUpdate

        texts = [
            "Merci à tous : les premiers travaux ont commencé cette semaine.",
            "Nous avons reçu les devis. Les travaux reprendront après la saison des pluies.",
            "Une étape est franchie. Merci pour votre fidélité et votre prière.",
        ]
        rows = []
        for plan in plans:
            if plan.camp is None:
                continue
            for i, text in enumerate(texts[: self.rng.randint(1, 3)]):
                rows.append(FundUpdate(fund=plan.camp, author=plan.cure, body=text,
                                       created_at=self.ctx.now - datetime.timedelta(days=40 - 15 * i)))  # fmt: skip
        FundUpdate.objects.bulk_create(rows)

    def _closings(self, plans: list[ParishPlan]) -> int:
        from apps.core.exceptions import ApplicationError
        from apps.donations.models import MonthClosing
        from apps.donations.services_cloture import month_close

        created = []
        current = self.ctx.today.replace(day=1)
        for plan in plans:
            for month in calendrier.month_iter(self.ctx.start, current - datetime.timedelta(days=1)):
                if MonthClosing.objects.filter(node=plan.node, month=month).exists():
                    continue
                try:
                    created.append(month_close(node=plan.node, month=month).pk)
                except ApplicationError as exc:
                    self.ctx.note(f"Clôture {month:%Y-%m} de {plan.node.name} impossible : {exc}")
        self.ctx.track(MonthClosing, created)
        return len(created)

    # --- Remise à zéro -----------------------------------------------------------------------------

    def reset(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.donations.models import (
            CashCollection,
            CashDeposit,
            CuriaRemittance,
            Donation,
            DonationActivation,
            DonationAdjustment,
            Fund,
            MonthClosing,
            Payout,
            ReceiptSequence,
        )
        from apps.hierarchy.models import AuditEvent

        fund_ids = ctx.tracked_ids(Fund)
        closing_ids = ctx.tracked_ids(MonthClosing)
        AuditEvent.objects.filter(action="dons.cloture_mois", target_id__in=closing_ids).delete()
        MonthClosing.objects.filter(pk__in=closing_ids).delete()
        DonationAdjustment.objects.filter(Q(pk__in=ctx.tracked_ids(DonationAdjustment)) | Q(fund_id__in=fund_ids)).delete()
        n_dons = 0
        for qs in (Donation.objects.filter(fund_id__in=fund_ids), ctx.tracked(Donation)):
            n_dons += qs.count()
            qs.delete()
        collections = CashCollection.objects.filter(Q(pk__in=ctx.tracked_ids(CashCollection)) | Q(fund_id__in=fund_ids))
        n_cash = collections.count()
        collections.delete()
        CashDeposit.objects.filter(pk__in=ctx.tracked_ids(CashDeposit)).delete()
        CuriaRemittance.objects.filter(Q(pk__in=ctx.tracked_ids(CuriaRemittance)) | Q(fund_id__in=fund_ids)).delete()
        Payout.objects.filter(pk__in=ctx.tracked_ids(Payout)).delete()
        Fund.objects.filter(pk__in=fund_ids, parent__isnull=False).delete()
        Fund.objects.filter(pk__in=fund_ids).delete()
        ReceiptSequence.objects.filter(pk__in=ctx.tracked_ids(ReceiptSequence)).delete()
        DonationActivation.objects.filter(pk__in=ctx.tracked_ids(DonationActivation)).delete()
        return {"dons": n_dons, "quetes": n_cash, "fonds": len(fund_ids)}

    # --- Vérification ------------------------------------------------------------------------------

    def verify(self, ctx: SeedContext) -> list[Check]:
        from apps.donations.enums import DonationStatus as S
        from apps.donations.models import Donation, DonationAdjustment, MonthClosing
        from apps.donations.selectors_analyse import donations_analysis, month_totals, period_parse

        checks: list[Check] = []
        parishes = ctx.parishes()
        mismatches, months = [], 0
        for node in parishes:
            for month in calendrier.month_iter(ctx.start, ctx.today):
                end = (month + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
                raw = (
                    Donation.objects.filter(fund__node=node, status__in=[S.CONFIRME, S.REMBOURSE],
                                            value_date__gte=month, value_date__lte=end)
                    .aggregate(s=Sum("amount"))["s"] or 0
                ) + (
                    DonationAdjustment.objects.filter(fund__node=node, value_date__gte=month, value_date__lte=end)
                    .aggregate(s=Sum("amount"))["s"] or 0
                )  # fmt: skip
                totals = month_totals(node=node, month=month)
                closing = MonthClosing.objects.filter(node=node, month=month).first()
                months += 1
                if totals["collecte"] != raw or (closing and closing.totals.get("collecte") != raw):
                    mismatches.append(f"{node.name} {month:%Y-%m}")
        checks.append(
            Check("Somme des opérations = synthèse (et clôtures)", not mismatches,
                  f"{months} mois-paroisses contrôlés" + (f", écarts : {', '.join(mismatches[:5])}" if mismatches else ""))
        )  # fmt: skip
        if ctx.start <= SEPT_FIRST and ctx.today >= SEPT_LAST_SUNDAY:
            s = donations_analysis(node=parishes[0], level="paroisse", period=period_parse("mois", "2026-09"))["synthese"]
            got = (s["collecte"], s["en_ligne"], s["especes"], s["nombre_dons_en_ligne"], s["nombre_quetes"])
            checks.append(Check("Septembre 2026 à Saint-Dominique = jeu de la spec", got == (1_214_830, 356_330, 858_500, 47, 9),
                                f"collecté {_n(got[0])} (en ligne {_n(got[1])}, espèces {_n(got[2])}), {got[3]} dons, {got[4]} quêtes"))  # fmt: skip
        total = Donation.objects.filter(fund__node__in=parishes).count()
        failed = Donation.objects.filter(fund__node__in=parishes, status__in=[S.ECHOUE, S.EXPIRE]).count()
        online = Donation.objects.filter(fund__node__in=parishes, channel="en_ligne").count()
        checks.append(Check("Volume des dons", total > 0, f"{total} dons, dont {online} en ligne ; {failed} échoués ou expirés ({100 * failed // max(online, 1)} % des paiements en ligne)"))
        return checks


def _n(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _diocese() -> Any:
    from apps.hierarchy.models import Node

    return Node.objects.get(code="DAK")
