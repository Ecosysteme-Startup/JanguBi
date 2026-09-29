"""Calendrier réel du semis (plan §4) : grandes fêtes, pèlerinage de Popenguine, quêtes impérées
diocésaines. Pâques vient de ``apps.liturgy.calendar`` (le même que l'app)."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

D = datetime.date


def _sunday_on_or_after(day: D) -> D:
    return day + datetime.timedelta(days=(6 - day.weekday()) % 7)


def feasts(year: int) -> dict[D, tuple[str, float]]:
    """Jour → (fête, multiplicateur de la quête). Pentecôte : une partie des fidèles est à Popenguine."""
    from apps.liturgy.calendar import easter

    e = easter(year)
    td = datetime.timedelta
    return {
        e - td(days=46): ("Mercredi des Cendres", 1.3),
        e - td(days=7): ("Rameaux", 1.6),
        e - td(days=3): ("Jeudi saint", 1.4),
        e: ("Pâques", 2.4),
        e + td(days=39): ("Ascension", 1.3),
        e + td(days=49): ("Pentecôte (pèlerinage de Popenguine)", 0.75),
        D(year, 8, 15): ("Assomption", 1.8),
        D(year, 11, 1): ("Toussaint", 1.5),
        D(year, 12, 25): ("Noël", 2.6),
        D(year, 1, 1): ("Sainte Marie, Mère de Dieu", 1.3),
    }


def is_feast_day(day: D) -> tuple[str, float] | None:
    return feasts(day.year).get(day)


@dataclass(frozen=True)
class Imperee:
    day: D
    title: str
    description: str
    anticipee: bool


def imperees(start: D, end: D) -> list[Imperee]:
    """Quêtes impérées de l'archidiocèse (dates diocésaines usuelles), entre ``start`` et ``end``."""
    from apps.liturgy.calendar import easter

    out: list[Imperee] = []
    for year in range(start.year, end.year + 1):
        e = easter(year)
        td = datetime.timedelta
        oct_last_sundays = [D(year, 10, d) for d in range(1, 32) if D(year, 10, d).weekday() == 6]
        items = [
            (e - td(days=14), "Carême de partage", "Solidarité avec les plus pauvres du diocèse.", True),
            (e + td(days=21), "Quête pour les vocations", "Formation des séminaristes et des novices.", True),
            (e + td(days=49), "Pèlerinage marial de Popenguine", "Organisation et accueil des pèlerins.", False),
            (_sunday_on_or_after(D(year, 6, 26)), "Denier de Saint-Pierre", "Charité du Saint-Père.", True),
            (oct_last_sundays[-2], "Journée missionnaire mondiale", "Œuvres pontificales missionnaires.", True),
        ]
        for day, title, description, anticipee in items:
            if start <= day <= end:
                out.append(Imperee(day, f"Quête impérée · {title}", description, anticipee))
    return sorted(out, key=lambda i: i.day)


def month_iter(start: D, end: D) -> list[D]:
    months, cur = [], start.replace(day=1)
    while cur <= end:
        months.append(cur)
        cur = (cur + datetime.timedelta(days=32)).replace(day=1)
    return months
