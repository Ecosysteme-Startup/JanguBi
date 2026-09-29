"""Jeu de septembre 2026 de Saint-Dominique (spec ECRANS-TABLEAU-DE-BORD-DONS §2), partagé par les tests
d'analyse (``tests/dataset_septembre.py``) et les données de test réalistes (``seeders.py``) : les écrans en
recette se comparent ainsi aux maquettes au franc près.

Collecté 1 214 830 = en ligne 356 330 (47 dons) + espèces 858 500 (9 quêtes) ; une quête à confirmer de 64 000.
"""

import datetime
from dataclasses import dataclass

UTC = datetime.UTC
SUNDAYS = {6: datetime.date(2026, 9, 6), 13: datetime.date(2026, 9, 13), 20: datetime.date(2026, 9, 20),
           27: datetime.date(2026, 9, 27)}  # fmt: skip
WEEK_START = {6: datetime.date(2026, 9, 1), 13: datetime.date(2026, 9, 7), 20: datetime.date(2026, 9, 14),
              27: datetime.date(2026, 9, 21)}  # fmt: skip

# Dons en ligne confirmés : (type de fonds, semaine) → montant (§2.3, colonnes en ligne).
ONLINE_CELLS: list[tuple[str, int, int]] = [
    ("dom", 6, 3_000), ("dom", 13, 2_905), ("dom", 20, 3_000), ("dom", 27, 38_500),
    ("imp", 27, 28_525),
    ("camp", 6, 60_500), ("camp", 13, 71_345), ("camp", 20, 64_305), ("camp", 27, 40_250),
    ("contrib", 6, 8_000), ("contrib", 13, 10_000), ("contrib", 20, 18_000), ("contrib", 27, 8_000),
]  # fmt: skip
# Groupes (source, moyen) : (nombre, montant), cohérents avec les marges du §2.4.
ONLINE_GROUPS: list[tuple[str, str, int, int]] = [
    ("app_ios", "carte", 4, 41_500),
    ("app_ios", "wave", 4, 20_000),
    ("web", "orange_money", 6, 46_380),
    ("web", "wave", 7, 49_450),
    ("app_android", "orange_money", 8, 60_000),
    ("app_android", "wave", 18, 139_000),
]
# Quêtes validées : (type, date de la messe, messe, lieu, montant). Église 775 000 (7), chapelle 83 500 (2).
CASH: list[tuple[str, datetime.date, str, str, int]] = [
    ("dom", datetime.date(2026, 9, 20), "Messe de 7 h", "eglise", 52_000),
    ("dom", datetime.date(2026, 9, 20), "Messe de 11 h 30", "eglise", 77_000),
    ("dom", datetime.date(2026, 9, 20), "Messe de 10 h", "chapelle", 38_500),
    ("dom", datetime.date(2026, 9, 20), "Messe de 17 h", "chapelle", 45_000),
    ("imp", datetime.date(2026, 9, 26), "Messe anticipée de 18 h 30", "eglise", 112_500),
    ("imp", datetime.date(2026, 9, 27), "Messe de 7 h", "eglise", 86_475),
    ("imp", datetime.date(2026, 9, 27), "Messe de 9 h 30", "eglise", 96_725),
    ("imp", datetime.date(2026, 9, 27), "Messe de 11 h 30", "eglise", 231_900),
    ("imp", datetime.date(2026, 9, 27), "Messe de 18 h 30", "eglise", 118_400),
]
FEES_TOTAL = 7_120
PAID_OUT_NET = 301_480
CAMPAIGN_BEFORE = [(datetime.date(2026, 6, 15), 214_000), (datetime.date(2026, 7, 15), 268_000),
                   (datetime.date(2026, 8, 15), 468_000)]  # fmt: skip
CAMPAIGN_DONATIONS = 57


@dataclass
class _Entry:
    group: int
    cell: int
    amount: int


def transport() -> list[_Entry]:
    """Répartit les groupes (source, moyen) sur les cellules (fonds, semaine) : coin nord-ouest, puis
    découpage en dons pour respecter les nombres de chaque groupe."""
    rows = [g[3] for g in ONLINE_GROUPS]
    cols = [c[2] for c in ONLINE_CELLS]
    assert sum(rows) == sum(cols) == 356_330
    entries: list[_Entry] = []
    i = j = 0
    while i < len(rows) and j < len(cols):
        take = min(rows[i], cols[j])
        entries.append(_Entry(i, j, take))
        rows[i] -= take
        cols[j] -= take
        if rows[i] == 0:
            i += 1
        if cols[j] == 0:
            j += 1
    donations: list[_Entry] = []
    for g, (_, _, count, _) in enumerate(ONLINE_GROUPS):
        mine = [e for e in entries if e.group == g and e.amount > 0]
        pieces = {id(e): 1 for e in mine}
        extra = count - len(mine)
        assert extra >= 0, "groupe trop petit pour ses cellules"
        while extra:
            e = max(mine, key=lambda x: x.amount / pieces[id(x)])  # la plus grosse part par don
            pieces[id(e)] += 1
            extra -= 1
        for e in mine:
            n = pieces[id(e)]
            base, rest = divmod(e.amount, n)
            for p in range(n):
                donations.append(_Entry(e.group, e.cell, base + (rest if p == 0 else 0)))
    return donations


def subset(values: list[int], target: int) -> set[int]:
    """Indices dont la somme vaut ``target`` (sous-ensemble, programmation dynamique)."""
    reach: dict[int, tuple[int, int] | None] = {0: None}
    for idx, v in enumerate(values):
        for s in list(reach):
            if s + v <= target and s + v not in reach:
                reach[s + v] = (s, idx)
    assert target in reach, "reversement impossible à composer"
    chosen, s = set(), target
    while reach[s] is not None:
        prev, idx = reach[s]  # type: ignore[misc]
        chosen.add(idx)
        s = prev
    return chosen
