"""Dons : lectures analytiques des tableaux de bord (V2 ; spec ECRANS-TABLEAU-DE-BORD-DONS §5).

Règles appliquées ici, côté serveur, jamais par le client (décisions du 27/09/2026) :
- aucun nom de donateur, à aucun niveau ;
- au-dessus de la paroisse (diocèse, doyenné) : montants arrondis au millier, pourcentages entiers
  calculés sur les valeurs exactes ; pas de seuil k ni de règle de dominance ;
- paroisses toujours en ordre alphabétique ; aucune liste n'est triée par montant ;
- toutes les séries se fondent sur la date de valeur (jour de la messe, date de confirmation) ;
- « à traiter » trié par échéance croissante ;
- plateforme : aucun montant, même agrégé (``platform_activity``).
"""

import datetime
import math
import re
import statistics
import unicodedata
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db.models import Count, Max, Min, Q, QuerySet, Sum
from django.db.models.functions import Coalesce, ExtractHour, ExtractIsoWeekDay, TruncDate
from django.utils import timezone

from apps.core.exceptions import ApplicationError
from apps.donations.enums import (
    PARISH_TYPES,
    CashCollectionStatus,
    DonationChannel,
    DonationSource,
    DonationStatus,
    FundKind,
    FundStatus,
    PaymentMethod,
    RemittanceStatus,
    WebhookStatus,
)
from apps.donations.models import (
    CashCollection,
    CuriaRemittance,
    Donation,
    DonationActivation,
    Fund,
    PaymentWebhookEvent,
    Payout,
)
from apps.hierarchy.models import Node, PlaceOfWorship

# Ordres canoniques, fixes (jamais un tri par montant).
FUND_KIND_ORDER = [
    FundKind.QUETE_DOMINICALE,
    FundKind.QUETE_IMPEREE,
    FundKind.CAMPAGNE,
    FundKind.CONTRIBUTION_ANNUELLE,
]
SOURCE_ORDER = [
    DonationSource.APP_IOS,
    DonationSource.APP_ANDROID,
    DonationSource.WEB,
    DonationSource.QR,
    DonationSource.INCONNU,
]
ALWAYS_SHOWN_SOURCES = {DonationSource.APP_IOS, DonationSource.APP_ANDROID, DonationSource.WEB}
METHOD_ORDER = [
    PaymentMethod.WAVE,
    PaymentMethod.ORANGE_MONEY,
    PaymentMethod.FREE_MONEY,
    PaymentMethod.CARTE,
    PaymentMethod.AUTRE,
    PaymentMethod.INCONNU,
]
ALWAYS_SHOWN_METHODS = {PaymentMethod.WAVE, PaymentMethod.ORANGE_MONEY, PaymentMethod.FREE_MONEY, PaymentMethod.CARTE}
PENDING = [DonationStatus.INITIE, DonationStatus.EN_ATTENTE]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre"]  # fmt: skip
TODO_ORDER = [
    "quete_a_confirmer",
    "paiements_en_attente",
    "paiement_tardif",
    "especes_a_deposer",
    "remise_curie",
    "remise_a_confirmer",
    "cloture_mois",
]


# --- Période --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Period:
    kind: str  # semaine | mois | trimestre | annee
    code: str  # 2026-W39 | 2026-09 | 2026-T3 | 2026
    start: datetime.date
    end: datetime.date  # inclus
    label: str

    def shifted(self, steps: int) -> "Period":
        """Même grain, ``steps`` périodes plus tôt (négatif) ou plus tard."""
        if self.kind == "semaine":
            return period_parse("semaine", _week_code(self.start + datetime.timedelta(weeks=steps)))
        if self.kind == "annee":
            return period_parse("annee", str(self.start.year + steps))
        months = 3 if self.kind == "trimestre" else 1
        index = self.start.year * 12 + self.start.month - 1 + steps * months
        year, month = divmod(index, 12)
        if self.kind == "trimestre":
            return period_parse("trimestre", f"{year}-T{month // 3 + 1}")
        return period_parse("mois", f"{year}-{month + 1:02d}")


def _week_code(day: datetime.date) -> str:
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _month_end(year: int, month: int) -> datetime.date:
    first_next = datetime.date(year + month // 12, month % 12 + 1, 1)
    return first_next - datetime.timedelta(days=1)


def period_parse(kind: str, code: str | None = None) -> Period:
    """``mois`` : AAAA-MM ; ``trimestre`` : AAAA-Tn ; ``annee`` : AAAA ; ``semaine`` : AAAA-Www (ISO).
    Sans code : la période en cours."""
    today = timezone.localdate()
    if not code:
        code = {
            "semaine": _week_code(today),
            "mois": f"{today:%Y-%m}",
            "trimestre": f"{today.year}-T{(today.month - 1) // 3 + 1}",
            "annee": str(today.year),
        }.get(kind, "")
    try:
        if kind == "mois" and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", code):
            year, month = int(code[:4]), int(code[5:])
            return Period(kind, code, datetime.date(year, month, 1), _month_end(year, month), f"{MONTHS[month - 1]} {year}")
        if kind == "trimestre" and re.fullmatch(r"\d{4}-T[1-4]", code):
            year, quarter = int(code[:4]), int(code[-1])
            first = 3 * (quarter - 1) + 1
            label = f"{'1er' if quarter == 1 else f'{quarter}e'} trimestre {year}"
            return Period(kind, code, datetime.date(year, first, 1), _month_end(year, first + 2), label)
        if kind == "annee" and re.fullmatch(r"\d{4}", code):
            year = int(code)
            return Period(kind, code, datetime.date(year, 1, 1), datetime.date(year, 12, 31), f"année {year}")
        if kind == "semaine" and re.fullmatch(r"\d{4}-W\d{2}", code):
            start = datetime.date.fromisocalendar(int(code[:4]), int(code[6:]), 1)
            end = start + datetime.timedelta(days=6)
            label = f"semaine du {start.day} {MONTHS[start.month - 1]} au {end.day} {MONTHS[end.month - 1]} {end.year}"
            return Period(kind, code, start, end, label)
    except ValueError:
        pass
    raise ApplicationError(
        "Période invalide.", {"periode": kind, "date": code}, code="invalid_period"
    )


def _sub_periods(period: Period, today: datetime.date) -> tuple[str, list[tuple[datetime.date, datetime.date, str]]]:
    """Découpage de la tendance : jours d'une semaine, semaines (lundi → dimanche, libellées par
    leur dimanche) d'un mois, mois d'un trimestre ou d'une année. Les pas encore commencés sont omis."""
    buckets: list[tuple[datetime.date, datetime.date, str]] = []
    if period.kind == "semaine":
        grain = "jour"
        for i in range(7):
            day = period.start + datetime.timedelta(days=i)
            buckets.append((day, day, f"{['lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.', 'dim.'][i]} {day.day}"))
    elif period.kind == "mois":
        grain = "semaine"
        start = period.start
        while start <= period.end:
            sunday = start + datetime.timedelta(days=7 - start.isoweekday())
            end = min(sunday, period.end)
            label = f"au dim. {sunday.day}" if sunday.month == period.start.month else f"au {end.day} {MONTHS[end.month - 1]}"
            buckets.append((start, end, label))
            start = end + datetime.timedelta(days=1)
    else:
        grain = "mois"
        month = period.start
        while month <= period.end:
            buckets.append((month, _month_end(month.year, month.month), MONTHS[month.month - 1]))
            month = _month_end(month.year, month.month) + datetime.timedelta(days=1)
    return grain, [b for b in buckets if b[0] <= today]


# --- Outils ---------------------------------------------------------------------------------


def _sum(field: str, condition: Q | None = None) -> Coalesce:
    return Coalesce(Sum(field, filter=condition), 0)


def _pct(part: int, whole: int) -> int | None:
    return round(part * 100 / whole) if whole else None


def _alpha_key(name: str) -> str:
    """Tri alphabétique insensible aux accents et à la casse (« Sainte-Thérèse » après « Saint-Joseph »)."""
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()


class _Rounder:
    """Arrondi au millier au-dessus de la paroisse (demi à l'unité supérieure), exact sinon."""

    def __init__(self, unit: int) -> None:
        self.unit = unit

    def __call__(self, value: int | None) -> int | None:
        if value is None or self.unit == 1:
            return value
        return int(math.floor(value / self.unit + 0.5) * self.unit)


def _counted(scope: Q, start: datetime.date, end: datetime.date) -> QuerySet[Donation]:
    """Dons comptés dans « collecté » : confirmés, datés par leur date de valeur."""
    return Donation.objects.filter(scope, status=DonationStatus.CONFIRME, value_date__gte=start, value_date__lte=end)


def _scope(node: Node, level: str) -> Q:
    if level == "paroisse":
        return Q(fund__node=node)
    return Q(fund__node__path__startswith=node.path, fund__node__type__code__in=PARISH_TYPES)


# --- Blocs ----------------------------------------------------------------------------------


def _synthese(scope: Q, period: Period, level: str, node: Node, r: _Rounder) -> dict[str, Any]:
    qs = _counted(scope, period.start, period.end)
    online, cash = Q(channel=DonationChannel.EN_LIGNE), Q(channel=DonationChannel.ESPECES)
    t = qs.aggregate(
        collecte=_sum("amount"),
        en_ligne=_sum("amount", online),
        especes=_sum("amount", cash),
        nb_en_ligne=Count("id", filter=online),
        nb_quetes=Count("id", filter=cash),
    )
    total = t["collecte"]
    dest = {row["fund__destination"]: row["s"] for row in qs.values("fund__destination").annotate(s=Sum("amount"))}

    kinds: dict[str, dict[str, int]] = {k: {"en_ligne": 0, "especes": 0, "nombre": 0} for k in FUND_KIND_ORDER}
    for row in qs.values("fund__kind", "channel").annotate(s=Sum("amount"), n=Count("id")):
        slot = kinds.setdefault(row["fund__kind"], {"en_ligne": 0, "especes": 0, "nombre": 0})
        slot["en_ligne" if row["channel"] == DonationChannel.EN_LIGNE else "especes"] += row["s"]
        slot["nombre"] += row["n"]
    par_type = [
        {"type": k, "libelle": FundKind(k).label, "en_ligne": r(v["en_ligne"]), "especes": r(v["especes"]),
         "total": r(v["en_ligne"] + v["especes"]), "nombre": v["nombre"], "part": _pct(v["en_ligne"] + v["especes"], total)}
        for k, v in kinds.items()
    ]  # fmt: skip

    par_fonds = None
    if level == "paroisse":
        rows: dict[Any, dict[str, Any]] = {}
        for row in qs.values("fund_id", "fund__title", "fund__kind", "fund__destination", "channel").annotate(
            s=Sum("amount"), n=Count("id")
        ):
            item = rows.setdefault(
                row["fund_id"],
                {"fonds_id": row["fund_id"], "titre": row["fund__title"], "type": row["fund__kind"],
                 "destination": row["fund__destination"], "en_ligne": 0, "especes": 0, "nombre": 0},
            )  # fmt: skip
            item["en_ligne" if row["channel"] == DonationChannel.EN_LIGNE else "especes"] += row["s"]
            item["nombre"] += row["n"]
        par_fonds = sorted(
            ({**v, "total": v["en_ligne"] + v["especes"], "part": _pct(v["en_ligne"] + v["especes"], total)}
             for v in rows.values()),
            key=lambda v: (FUND_KIND_ORDER.index(v["type"]) if v["type"] in FUND_KIND_ORDER else 99, _alpha_key(v["titre"])),
        )  # fmt: skip

    sources = {row["source"]: row for row in qs.filter(online).values("source").annotate(s=Sum("amount"), n=Count("id"))}
    par_source = [
        {"source": s, "libelle": DonationSource(s).label, "total": r(sources.get(s, {}).get("s", 0)),
         "nombre": sources.get(s, {}).get("n", 0), "part": _pct(sources.get(s, {}).get("s", 0), t["en_ligne"])}
        for s in SOURCE_ORDER
        if s in ALWAYS_SHOWN_SOURCES or s in sources
    ]  # fmt: skip
    par_canal = [
        {"canal": DonationChannel.EN_LIGNE, "libelle": "En ligne", "total": r(t["en_ligne"]), "nombre": t["nb_en_ligne"],
         "part": _pct(t["en_ligne"], total), "sources": par_source},
        {"canal": DonationChannel.ESPECES, "libelle": "Espèces", "total": r(t["especes"]), "nombre": t["nb_quetes"],
         "part": _pct(t["especes"], total), "sources": []},
    ]  # fmt: skip

    methods = {row["payment_method"]: row for row in qs.filter(online).values("payment_method").annotate(
        s=Sum("amount"), n=Count("id"))}  # fmt: skip
    par_moyen = [
        {"moyen": m, "libelle": PaymentMethod(m).label, "total": r(methods.get(m, {}).get("s", 0)),
         "nombre": methods.get(m, {}).get("n", 0), "part": _pct(methods.get(m, {}).get("s", 0), t["en_ligne"])}
        for m in METHOD_ORDER
        if m in ALWAYS_SHOWN_METHODS or m in methods
    ]  # fmt: skip

    par_lieu = None
    if level == "paroisse":
        by_place: dict[Any, dict[str, int]] = {}
        for row in qs.values("place_id", "channel").annotate(s=Sum("amount"), n=Count("id")):
            slot = by_place.setdefault(row["place_id"], {"en_ligne": 0, "especes": 0, "nombre": 0})
            slot["en_ligne" if row["channel"] == DonationChannel.EN_LIGNE else "especes"] += row["s"]
            slot["nombre"] += row["n"]
        places = PlaceOfWorship.objects.filter(node=node).filter(Q(is_active=True) | Q(pk__in=[k for k in by_place if k]))
        par_lieu = []
        for place in places.order_by("-is_main", "name"):
            v = by_place.get(place.pk, {"en_ligne": 0, "especes": 0, "nombre": 0})
            par_lieu.append({"lieu_id": place.pk, "nom": place.name, "en_ligne": v["en_ligne"], "especes": v["especes"],
                             "total": v["en_ligne"] + v["especes"], "nombre": v["nombre"],
                             "part": _pct(v["en_ligne"] + v["especes"], total)})  # fmt: skip
        if None in by_place:
            v = by_place[None]
            par_lieu.append({"lieu_id": None, "nom": "Lieu non renseigné", "en_ligne": v["en_ligne"],
                             "especes": v["especes"], "total": v["en_ligne"] + v["especes"], "nombre": v["nombre"],
                             "part": _pct(v["en_ligne"] + v["especes"], total)})  # fmt: skip

    return {
        "collecte": r(total),
        "en_ligne": r(t["en_ligne"]),
        "especes": r(t["especes"]),
        "nombre_dons_en_ligne": t["nb_en_ligne"],
        "nombre_quetes": t["nb_quetes"],
        "par_destination": {"paroisse": r(dest.get("paroisse", 0)), "curie": r(dest.get("curie", 0))},
        "par_type_fonds": par_type,
        "par_fonds": par_fonds,
        "par_canal": par_canal,
        "par_moyen": par_moyen,
        "par_lieu": par_lieu,
    }


def _tendance(scope: Q, period: Period, r: _Rounder, today: datetime.date) -> dict[str, Any]:
    grain, buckets = _sub_periods(period, today)
    rows = (
        _counted(scope, period.start, period.end)
        .values("value_date", "fund__kind", "channel")
        .annotate(s=Sum("amount"))
    )
    points = []
    for start, end, label in buckets:
        kinds = {k: 0 for k in FUND_KIND_ORDER}
        online = cash = 0
        for row in rows:
            if start <= row["value_date"] <= end:
                kinds[row["fund__kind"]] = kinds.get(row["fund__kind"], 0) + row["s"]
                if row["channel"] == DonationChannel.EN_LIGNE:
                    online += row["s"]
                else:
                    cash += row["s"]
        points.append({"debut": start, "fin": end, "libelle": label, "total": r(online + cash), "en_ligne": r(online),
                       "especes": r(cash), "par_type_fonds": {k: r(v) for k, v in kinds.items()}})  # fmt: skip
    return {"grain": grain, "points": points}


def _todo(item_type: str, due: datetime.date, label: str, **extra: Any) -> dict[str, Any]:
    return {"type": item_type, "echeance": due, "libelle": label, "nombre": extra.get("nombre", 1),
            "montant": extra.get("montant"), "depuis": extra.get("depuis"), "paroisse": extra.get("paroisse"),
            "objet_id": extra.get("objet_id")}  # fmt: skip


def _brief(node: Node) -> dict[str, Any]:
    return {"id": node.pk, "nom": node.name}


def _imperee_rows(scope_nodes: Q) -> list[dict[str, Any]]:
    """Déclinaisons paroissiales de quêtes impérées, avec espèces validées et remises (montants exacts :
    argent de la curie)."""
    funds = Fund.objects.filter(scope_nodes, kind=FundKind.QUETE_IMPEREE, parent__isnull=False).select_related(
        "node", "parent"
    )
    result = []
    for fund in funds:
        agg = Donation.objects.filter(fund=fund, status=DonationStatus.CONFIRME).aggregate(
            en_ligne=_sum("amount", Q(channel=DonationChannel.EN_LIGNE)),
            especes=_sum("amount", Q(channel=DonationChannel.ESPECES)),
        )
        rem = CuriaRemittance.objects.filter(fund=fund).aggregate(
            confirme=_sum("amount", Q(status=RemittanceStatus.CONFIRMEE)),
            declare=_sum("amount", Q(status=RemittanceStatus.DECLAREE)),
        )
        result.append({"fund": fund, **agg, "remis": rem["confirme"], "declare": rem["declare"],
                       "reste": max(agg["especes"] - rem["confirme"] - rem["declare"], 0)})  # fmt: skip
    return result


def _a_traiter_paroisse(node: Node, today: datetime.date) -> list[dict[str, Any]]:
    items = []
    for c in CashCollection.objects.filter(node=node, status=CashCollectionStatus.SAISIE).select_related("place"):
        where = f"{c.place.name}, " if c.place else ""
        items.append(_todo("quete_a_confirmer", c.mass_date + datetime.timedelta(days=settings.DONATIONS_CASH_VALIDATE_DAYS),
                           f"Quête à confirmer : {where}{c.mass_label}, {c.mass_date:%d/%m}", montant=c.amount,
                           depuis=c.created_at, objet_id=str(c.pk)))  # fmt: skip
    pending = Donation.objects.filter(fund__node=node, channel=DonationChannel.EN_LIGNE, status__in=PENDING).aggregate(
        n=Count("id"), s=_sum("amount"), oldest=Min("created_at")
    )
    if pending["n"]:
        due = timezone.localtime(pending["oldest"] + datetime.timedelta(hours=settings.DONATIONS_EXPIRE_HOURS)).date()
        items.append(_todo("paiements_en_attente", due, f"{pending['n']} paiement(s) en attente de confirmation",
                           nombre=pending["n"], montant=pending["s"], depuis=pending["oldest"]))  # fmt: skip
    undeposited = CashCollection.objects.filter(
        node=node, status=CashCollectionStatus.VALIDEE, deposit__isnull=True
    ).aggregate(n=Count("id"), s=_sum("amount"), oldest=Min("mass_date"), since=Min("validated_at"))
    if undeposited["n"]:
        due = undeposited["oldest"] + datetime.timedelta(days=settings.DONATIONS_CASH_DEPOSIT_DAYS)
        items.append(_todo("especes_a_deposer", due, "Espèces à déposer en banque", nombre=undeposited["n"],
                           montant=undeposited["s"], depuis=undeposited["since"]))  # fmt: skip
    for row in _imperee_rows(Q(node=node)):
        if row["reste"] > 0:
            fund = row["fund"]
            due = fund.remit_by or fund.starts_on or today
            items.append(_todo("remise_curie", due, f"{fund.title} : espèces à remettre à la curie",
                               montant=row["reste"], objet_id=str(fund.pk)))  # fmt: skip
    return items


def _a_traiter_diocese(node: Node, today: datetime.date) -> list[dict[str, Any]]:
    items = []
    parishes = Q(node__path__startswith=node.path)
    for rem in CuriaRemittance.objects.filter(parishes, status=RemittanceStatus.DECLAREE).select_related("node", "fund"):
        due = rem.remitted_on + datetime.timedelta(days=settings.DONATIONS_REMITTANCE_CONFIRM_DAYS)
        items.append(_todo("remise_a_confirmer", due, f"Remise de {rem.node.name} à confirmer ({rem.fund.title})",
                           montant=rem.amount, depuis=rem.created_at, paroisse=_brief(rem.node),
                           objet_id=str(rem.pk)))  # fmt: skip
    for row in _imperee_rows(parishes):
        fund = row["fund"]
        if row["reste"] > 0:
            items.append(_todo("remise_curie", fund.remit_by or fund.starts_on or today,
                               f"{fund.title} : espèces de {fund.node.name} à remettre", montant=row["reste"],
                               paroisse=_brief(fund.node), objet_id=str(fund.pk)))  # fmt: skip
    pending_cash = (
        CashCollection.objects.filter(parishes, status=CashCollectionStatus.SAISIE)
        .values("node_id", "node__name")
        .annotate(n=Count("id"), oldest=Min("mass_date"))
    )
    for row in pending_cash:
        items.append(_todo("quete_a_confirmer",
                           row["oldest"] + datetime.timedelta(days=settings.DONATIONS_CASH_VALIDATE_DAYS),
                           f"{row['node__name']} : {row['n']} quête(s) à confirmer", nombre=row["n"],
                           paroisse={"id": row["node_id"], "nom": row["node__name"]}))  # fmt: skip
    return items


def _sort_todo(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda i: (i["echeance"], TODO_ORDER.index(i["type"]) if i["type"] in TODO_ORDER else 99,
                       _alpha_key((i["paroisse"] or {}).get("nom", "")), i["libelle"]),
    )  # fmt: skip


def _evolution(parish: Node, period: Period, opened_on: datetime.date) -> str | None:
    """La paroisse comparée à elle-même : période analysée face à la moyenne des trois précédentes,
    à ±10 %. ``None`` tant que trois périodes complètes n'ont pas suivi l'ouverture de la collecte
    (pilote lancé en septembre 2026)."""
    scope = Q(fund__node=parish)
    previous = []
    for step in (-1, -2, -3):
        p = period.shifted(step)
        if p.start < opened_on:
            return None
        previous.append(_counted(scope, p.start, p.end).aggregate(s=_sum("amount"))["s"])
    if any(v == 0 for v in previous):
        return None
    current = _counted(scope, period.start, period.end).aggregate(s=_sum("amount"))["s"]
    mean = statistics.mean(previous)
    if current > mean * 1.1:
        return "en_hausse"
    if current < mean * 0.9:
        return "en_baisse"
    return "stable"


def _opened_on(activation: DonationActivation) -> datetime.date:
    return activation.authorization_date or timezone.localdate(activation.created_at)


def _paroisses(node: Node, period: Period, r: _Rounder) -> dict[str, Any]:
    activations = DonationActivation.objects.filter(
        node__path__startswith=node.path, node__type__code__in=PARISH_TYPES
    ).select_related("node")
    rows: list[dict[str, Any]] = []
    for activation in activations:
        parish = activation.node
        pending = CashCollection.objects.filter(node=parish, status=CashCollectionStatus.SAISIE).count()
        if not activation.enabled:
            rows.append({"id": parish.pk, "nom": parish.name, "statut_collecte": "en_preparation", "collecte": None,
                         "part_en_ligne": None, "quetes_a_valider": None, "evolution": None})  # fmt: skip
            continue
        t = _counted(Q(fund__node=parish), period.start, period.end).aggregate(
            s=_sum("amount"), online=_sum("amount", Q(channel=DonationChannel.EN_LIGNE))
        )
        rows.append({"id": parish.pk, "nom": parish.name, "statut_collecte": "ouverte", "collecte": r(t["s"]),
                     "part_en_ligne": _pct(t["online"], t["s"]), "quetes_a_valider": pending,
                     "evolution": _evolution(parish, period, _opened_on(activation))})  # fmt: skip
    rows.sort(key=lambda row: _alpha_key(str(row["nom"])))
    opened = sum(1 for row in rows if row["statut_collecte"] == "ouverte")
    return {
        "compteurs": {"engagees": len(rows), "collecte_ouverte": opened, "en_preparation": len(rows) - opened},
        "lignes": rows,
    }


def _quetes_imperees(scope_nodes: Q, period: Period) -> list[dict[str, Any]]:
    """Quêtes impérées dont la date tombe dans la période ; lignes par paroisse, alphabétiques."""
    groups: dict[Any, dict[str, Any]] = {}
    for row in _imperee_rows(scope_nodes):
        fund = row["fund"]
        parent = fund.parent
        day = parent.starts_on
        if day is None or not (period.start <= day <= period.end or (parent.ends_on and period.start <= parent.ends_on
                                                                     and day <= period.end)):  # fmt: skip
            continue
        group = groups.setdefault(parent.pk, {
            "fonds_id": parent.pk, "titre": parent.title, "date": parent.starts_on, "echeance": parent.remit_by,
            "messe_anticipee_incluse": getattr(parent, "messe_anticipee_incluse", False), "paroisses": [],
        })  # fmt: skip
        total = row["en_ligne"] + row["especes"]
        group["paroisses"].append({
            "id": fund.node_id, "nom": fund.node.name, "en_ligne": row["en_ligne"], "especes": row["especes"],
            "total": total, "remis": row["remis"], "remise_declaree": row["declare"], "reste_a_remettre": row["reste"],
            "part_remise": _pct(row["remis"], row["especes"]),
        })  # fmt: skip
    result = sorted(groups.values(), key=lambda g: (g["date"], _alpha_key(g["titre"])))
    for group in result:
        group["paroisses"].sort(key=lambda p: _alpha_key(p["nom"]))
    return result


def _tresorerie(node: Node, period: Period) -> dict[str, Any]:
    qs = _counted(Q(fund__node=node), period.start, period.end)
    online = qs.filter(channel=DonationChannel.EN_LIGNE).aggregate(
        paye=_sum("charged_amount"),
        frais=_sum("fee_amount"),
        frais_reels=_sum("fee_amount", Q(fee_is_actual=True)),
        net=_sum("net_amount"),
        reverse=_sum("net_amount", Q(payout__isnull=False)),
        en_attente=_sum("net_amount", Q(payout__isnull=True)),
        frais_couverts=Count("id", filter=Q(fees_covered=True)),
        nombre=Count("id"),
    )
    in_period = Q(node=node, mass_date__gte=period.start, mass_date__lte=period.end)
    cash = CashCollection.objects.filter(in_period).aggregate(
        validees=_sum("amount", Q(status=CashCollectionStatus.VALIDEE)),
        deposees=_sum("amount", Q(status=CashCollectionStatus.VALIDEE, deposit__isnull=False)),
        a_confirmer=_sum("amount", Q(status=CashCollectionStatus.SAISIE)),
    )
    return {
        "en_ligne": {
            "paye": online["paye"], "frais": online["frais"], "frais_reels": online["frais_reels"],
            "net": online["net"], "reverse": online["reverse"], "en_attente_reversement": online["en_attente"],
            "part_reversee": _pct(online["reverse"], online["net"]),
            "net_pour_100": _pct(online["net"], online["paye"]),
            "dons_frais_couverts": online["frais_couverts"], "nombre": online["nombre"],
        },
        "especes": {
            "validees": cash["validees"], "deposees": cash["deposees"],
            "en_caisse": cash["validees"] - cash["deposees"], "a_confirmer": cash["a_confirmer"],
        },
    }  # fmt: skip


def _paiements(node: Node, period: Period) -> dict[str, Any]:
    qs = Donation.objects.filter(
        fund__node=node, channel=DonationChannel.EN_LIGNE,
        created_at__date__gte=period.start, created_at__date__lte=period.end,
    )  # fmt: skip
    c = qs.aggregate(
        lances=Count("id"),
        confirmes=Count("id", filter=Q(status__in=[DonationStatus.CONFIRME, DonationStatus.REMBOURSE])),
        en_attente=Count("id", filter=Q(status__in=PENDING)),
        echoues=Count("id", filter=Q(status=DonationStatus.ECHOUE)),
        expires=Count("id", filter=Q(status=DonationStatus.EXPIRE)),
    )
    return {**c, "taux_confirmation": _pct(c["confirmes"], c["lances"])}


def _campagnes(node: Node, period: Period, today: datetime.date) -> list[dict[str, Any]]:
    funds = Fund.objects.filter(node=node, kind=FundKind.CAMPAGNE).exclude(status=FundStatus.BROUILLON)
    funds = funds.filter(Q(starts_on__isnull=True) | Q(starts_on__lte=period.end)).filter(
        Q(ends_on__isnull=True) | Q(ends_on__gte=period.start)
    )
    result = []
    end_of_view = min(today, period.end)
    for fund in funds.order_by("title"):
        done = Donation.objects.filter(fund=fund, status=DonationStatus.CONFIRME)
        agg = done.aggregate(reuni=_sum("amount"), nombre=Count("id"))
        in_period = done.filter(value_date__gte=period.start, value_date__lte=period.end).aggregate(s=_sum("amount"))
        recent = done.filter(value_date__gt=end_of_view - datetime.timedelta(days=28), value_date__lte=end_of_view)
        rythme = round(recent.aggregate(s=_sum("amount"))["s"] / 4)
        projection = None
        if fund.ends_on and fund.ends_on > end_of_view and fund.status == FundStatus.OUVERT:
            projection = agg["reuni"] + round(rythme * (fund.ends_on - end_of_view).days / 7)
        result.append({
            "fonds_id": fund.pk, "titre": fund.title, "objectif": fund.goal_amount, "reuni": agg["reuni"],
            "part": _pct(agg["reuni"], fund.goal_amount or 0), "nombre": agg["nombre"], "periode": in_period["s"],
            "debut": fund.starts_on, "fin": fund.ends_on, "statut": fund.status, "rythme_hebdo": rythme,
            "projection_fin": projection,
            "part_projection": _pct(projection, fund.goal_amount or 0) if projection is not None else None,
        })  # fmt: skip
    return result


def _notes(scope: Q, period: Period, level: str) -> list[str]:
    notes = []
    first_cash = Donation.objects.filter(scope, channel=DonationChannel.ESPECES, status=DonationStatus.CONFIRME).aggregate(
        d=Min("value_date")
    )["d"]
    if first_cash and period.start < first_cash <= period.end:
        notes.append(f"Les quêtes en espèces sont saisies sur Jàngu Bi depuis le {first_cash.day} "
                     f"{MONTHS[first_cash.month - 1]}.")  # fmt: skip
    first = Donation.objects.filter(scope, status=DonationStatus.CONFIRME).aggregate(d=Min("value_date"))["d"]
    if first is None or first > period.start - datetime.timedelta(days=365):
        since = (first or period.start).replace(day=1)
        notes.append(f"Comparaison avec l'an dernier disponible à partir de {MONTHS[since.month - 1]} {since.year + 1}.")
    if level != "paroisse":
        notes.append("Montants arrondis au millier : la somme des lignes peut différer du total.")
    notes.append("Montants en FCFA. Aucun nom de donateur dans cette vue.")
    return notes


# --- Point d'entrée -------------------------------------------------------------------------


def donations_analysis(*, node: Node, level: str, period: Period) -> dict[str, Any]:
    """Analyse des dons d'une paroisse (exacte) ou d'un diocèse / doyenné (arrondie au millier).
    L'appelant a vérifié les droits (``access``)."""
    today = timezone.localdate()
    unit = 1 if level == "paroisse" else 1000
    r = _Rounder(unit)
    scope = _scope(node, level)
    if level == "paroisse":
        todo = _a_traiter_paroisse(node, today)
        imperees = _quetes_imperees(Q(node=node), period)
    else:
        todo = _a_traiter_diocese(node, today)
        imperees = _quetes_imperees(Q(node__path__startswith=node.path), period)
    return {
        "niveau": level,
        "noeud": {"id": node.pk, "nom": node.name, "type": node.type.code},
        "periode": {"type": period.kind, "code": period.code, "debut": period.start, "fin": period.end,
                    "libelle": period.label},  # fmt: skip
        "genere_le": timezone.now(),
        "confidentialite": {"arrondi": unit, "noms_donateurs": False, "ordre_paroisses": "alphabetique",
                            "tri_par_montant": False},  # fmt: skip
        "synthese": _synthese(scope, period, level, node, r),
        "tendance": _tendance(scope, period, r, today),
        "a_traiter": _sort_todo(todo),
        "paroisses": _paroisses(node, period, r) if level != "paroisse" else None,
        "quetes_imperees": imperees,
        "tresorerie": _tresorerie(node, period) if level == "paroisse" else None,
        "paiements": _paiements(node, period) if level == "paroisse" else None,
        "campagnes": _campagnes(node, period, today) if level == "paroisse" else None,
        "notes": _notes(scope, period, level),
    }


# --- Plateforme : activité sans aucun montant -----------------------------------------------


def _percentile(values: list[float], q: float) -> int | None:
    """Rang le plus proche (``q`` entre 0 et 1), arrondi à l'entier."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(math.ceil(q * len(ordered)), 1)
    return round(ordered[rank - 1])


def _status_counts(qs: QuerySet[Donation]) -> dict[str, int]:
    return qs.aggregate(
        lances=Count("id"),
        confirmes=Count("id", filter=Q(status__in=[DonationStatus.CONFIRME, DonationStatus.REMBOURSE])),
        en_attente=Count("id", filter=Q(status__in=PENDING)),
        echoues=Count("id", filter=Q(status=DonationStatus.ECHOUE)),
        expires=Count("id", filter=Q(status=DonationStatus.EXPIRE)),
    )


def platform_activity(*, period: Period) -> dict[str, Any]:
    """Santé des paiements pour Numerisen : nombres, taux et délais seulement — **aucun montant**,
    même agrégé (décision du 27/09/2026). Par moyen, par source et par paroisse (ordre alphabétique)."""
    now = timezone.now()
    launched = Donation.objects.filter(
        channel=DonationChannel.EN_LIGNE, created_at__date__gte=period.start, created_at__date__lte=period.end
    )
    counts = _status_counts(launched)
    counts["rembourses"] = launched.filter(status=DonationStatus.REMBOURSE).count()
    oldest = Donation.objects.filter(channel=DonationChannel.EN_LIGNE, status__in=PENDING).aggregate(
        d=Min("created_at")
    )["d"]
    paiements = {
        **counts,
        "taux_confirmation": _pct(counts["confirmes"], counts["lances"]),
        "taux_echec": _pct(counts["echoues"] + counts["expires"], counts["lances"]),
        "plus_ancien_en_attente": oldest,
    }

    confirmed = Donation.objects.filter(
        channel=DonationChannel.EN_LIGNE, confirmed_at__date__gte=period.start, confirmed_at__date__lte=period.end
    )
    waits = [
        (c - a).total_seconds() for a, c in confirmed.values_list("created_at", "confirmed_at") if c and a and c >= a
    ]
    paid = Donation.objects.filter(
        payout__isnull=False, payout__paid_at__date__gte=period.start, payout__paid_at__date__lte=period.end
    ).values_list("confirmed_at", "payout__paid_at")
    payout_days = [(p - c).total_seconds() / 86_400 for c, p in paid if c and p and p >= c]
    delais = {
        "confirmation_mediane_s": _percentile(waits, 0.5),
        "confirmation_p95_s": _percentile(waits, 0.95),
        "reversement_moyen_jours": round(statistics.mean(payout_days)) if payout_days else None,
        "reversement_median_jours": _percentile(payout_days, 0.5),
        "echantillon_confirmation": len(waits),
    }

    by_day = {
        row["day"]: row
        for row in launched.annotate(day=TruncDate("created_at")).values("day").annotate(
            n=Count("id"),
            ok=Count("id", filter=Q(status__in=[DonationStatus.CONFIRME, DonationStatus.REMBOURSE])),
            wait=Count("id", filter=Q(status__in=PENDING)),
            ko=Count("id", filter=Q(status=DonationStatus.ECHOUE)),
            exp=Count("id", filter=Q(status=DonationStatus.EXPIRE)),
        )
    }
    par_jour = []
    day = period.start
    while day <= min(period.end, timezone.localdate(now)):
        row = by_day.get(day, {})
        par_jour.append({"date": day, "lances": row.get("n", 0), "confirmes": row.get("ok", 0),
                         "en_attente": row.get("wait", 0), "echoues": row.get("ko", 0),
                         "expires": row.get("exp", 0)})  # fmt: skip
        day += datetime.timedelta(days=1)

    methods = {
        row["payment_method"]: row
        for row in launched.values("payment_method").annotate(
            ok=Count("id", filter=Q(status__in=[DonationStatus.CONFIRME, DonationStatus.REMBOURSE])),
            ko=Count("id", filter=Q(status__in=[DonationStatus.ECHOUE, DonationStatus.EXPIRE])),
        )
    }
    par_moyen = [
        {"moyen": m, "libelle": PaymentMethod(m).label, "confirmes": methods.get(m, {}).get("ok", 0),
         "echecs": methods.get(m, {}).get("ko", 0),
         "taux_echec": _pct(methods.get(m, {}).get("ko", 0), methods.get(m, {}).get("ok", 0) + methods.get(m, {}).get("ko", 0))}
        for m in METHOD_ORDER
        if m in ALWAYS_SHOWN_METHODS or m in methods
    ]  # fmt: skip

    sources = {row["source"]: row for row in launched.values("source").annotate(
        n=Count("id"),
        ok=Count("id", filter=Q(status__in=[DonationStatus.CONFIRME, DonationStatus.REMBOURSE])),
        back=Count("id", filter=Q(returned_at__isnull=False)),
    )}  # fmt: skip
    par_source = [
        {"source": src, "libelle": DonationSource(src).label, "lances": sources.get(src, {}).get("n", 0),
         "confirmes": sources.get(src, {}).get("ok", 0),
         "taux_confirmation": _pct(sources.get(src, {}).get("ok", 0), sources.get(src, {}).get("n", 0)),
         "retours": sources.get(src, {}).get("back", 0),
         "taux_retour": _pct(sources.get(src, {}).get("back", 0), sources.get(src, {}).get("n", 0))}
        for src in SOURCE_ORDER
        if src in ALWAYS_SHOWN_SOURCES or src in sources
    ]  # fmt: skip

    par_paroisse = []
    for activation in DonationActivation.objects.select_related("node"):
        parish = activation.node
        c = _status_counts(launched.filter(fund__node=parish))
        last = Donation.objects.filter(fund__node=parish, channel=DonationChannel.EN_LIGNE,
                                       status=DonationStatus.CONFIRME).aggregate(d=Max("confirmed_at"))["d"]  # fmt: skip
        par_paroisse.append({
            "id": parish.pk, "nom": parish.name, "collecte_ouverte": activation.enabled, **c,
            "taux_confirmation": _pct(c["confirmes"], c["lances"]), "derniere_confirmation": last,
            "quetes_saisies": CashCollection.objects.filter(
                node=parish, mass_date__gte=period.start, mass_date__lte=period.end
            ).count(),
        })  # fmt: skip
    par_paroisse.sort(key=lambda row: _alpha_key(str(row["nom"])))

    events = PaymentWebhookEvent.objects.filter(
        received_at__date__gte=period.start, received_at__date__lte=period.end
    )
    ev = events.aggregate(
        recues=Count("id"),
        traitees=Count("id", filter=Q(status=WebhookStatus.TRAITE)),
        doublons=Count("id", filter=Q(status=WebhookStatus.DOUBLON)),
        rejetees=Count("id", filter=Q(status=WebhookStatus.REJETE)),
        erreurs=Count("id", filter=Q(status=WebhookStatus.ERREUR)),
        en_cours=Count("id", filter=Q(status=WebhookStatus.RECU)),
    )
    notifications = {**ev, "derniere_recue": PaymentWebhookEvent.objects.aggregate(d=Max("received_at"))["d"]}

    charge = [
        {"jour_semaine": row["dow"], "heure": row["hour"], "nombre": row["n"]}
        for row in launched.annotate(dow=ExtractIsoWeekDay("created_at"), hour=ExtractHour("created_at"))
        .values("dow", "hour")
        .annotate(n=Count("id"))
        .order_by("dow", "hour")
    ]

    return {
        "periode": {"type": period.kind, "code": period.code, "debut": period.start, "fin": period.end,
                    "libelle": period.label},  # fmt: skip
        "genere_le": now,
        "paiements": paiements,
        "delais": delais,
        "par_jour": par_jour,
        "par_moyen": par_moyen,
        "par_source": par_source,
        "par_paroisse": par_paroisse,
        "notifications": notifications,
        "charge": charge,
        "incidents": _platform_incidents(events),
        "reversements": {
            "a_rapprocher": Payout.objects.filter(status="recu").count(),
            "en_ecart": Payout.objects.filter(status="ecart").count(),
        },
    }


def _platform_incidents(events: QuerySet[PaymentWebhookEvent]) -> dict[str, Any]:
    """Incidents techniques, sans montant : notifications en erreur ou rejetées."""
    failed = events.filter(status__in=[WebhookStatus.ERREUR, WebhookStatus.REJETE])
    by_type: dict[str, int] = {}
    for code in failed.values_list("error_code", flat=True):
        by_type[code or "inconnu"] = by_type.get(code or "inconnu", 0) + 1
    return {
        "ouverts": failed.count(),
        "par_type": by_type,
        "liste": [
            {"type": e.error_code or e.status, "reference": e.external_ref, "paroisse": None, "detecte_le": e.received_at,
             "statut": "ouvert"}
            for e in failed.order_by("-received_at")[:20]
        ],  # fmt: skip
    }
