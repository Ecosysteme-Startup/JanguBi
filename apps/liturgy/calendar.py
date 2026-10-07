"""Calendrier liturgique romain calculé localement (SRS EF-PAR-02, ADR-008).

Fonctions pures, sans base ni réseau : temps liturgique, semaine, couleur, grandes
célébrations (solennités et fêtes du Seigneur), cycles des lectures. Les mémoires et les
calendriers propres (diocèse, pays) ne sont pas couverts ; les lectures elles-mêmes restent
fournies par la source configurée (``LITURGY_SOURCE``).

Réglages (valeurs par défaut conformes à l'usage francophone, à confirmer par la
Conférence épiscopale) : ``LITURGY_EPIPHANY_ON_SUNDAY`` (vrai), ``LITURGY_ASCENSION_ON_SUNDAY``
(faux), ``LITURGY_CORPUS_CHRISTI_ON_SUNDAY`` (vrai).
"""

import datetime
from dataclasses import asdict, dataclass
from typing import Any

from django.conf import settings

D = datetime.date
DAY = datetime.timedelta(days=1)

ADVENT, CHRISTMAS, ORDINARY, LENT, TRIDUUM, EASTER = "avent", "noel", "ordinaire", "careme", "triduum", "paques"
SEASON_LABELS = {
    ADVENT: "Temps de l'Avent",
    CHRISTMAS: "Temps de Noël",
    ORDINARY: "Temps ordinaire",
    LENT: "Temps du Carême",
    TRIDUUM: "Triduum pascal",
    EASTER: "Temps pascal",
}
SOLEMNITY, LORD_FEAST, FEAST, MEMORIAL, SUNDAY, WEEKDAY = (
    "solennite",
    "fete_du_seigneur",
    "fete",
    "memoire",
    "dimanche",
    "ferie",
)
WHITE, RED, GREEN, VIOLET, ROSE = "blanc", "rouge", "vert", "violet", "rose"
WEEKDAYS = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")
SEASON_OF = {ADVENT: "de l'Avent", LENT: "de Carême", EASTER: "de Pâques", ORDINARY: "du temps ordinaire"}


@dataclass(frozen=True)
class LiturgicalDay:
    date: D
    liturgical_year: int
    season: str
    season_label: str
    week: int | None
    celebration: str
    rank: str
    color: str
    sunday_cycle: str
    weekday_cycle: str

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["date"] = self.date.isoformat()
        return data


def _setting(name: str, default: bool) -> bool:
    return bool(getattr(settings, name, default))


def easter(year: int) -> D:
    """Dimanche de Pâques, calendrier grégorien (algorithme anonyme de Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month, day = divmod(h + l_ - 7 * m + 114, 31)
    return D(year, month, day + 1)


def _days_since_sunday(day: D) -> int:
    return (day.weekday() + 1) % 7


def advent_start(year: int) -> D:
    """Premier dimanche de l'Avent : quatre dimanches avant Noël (27 novembre – 3 décembre)."""
    christmas = D(year, 12, 25)
    fourth = christmas - datetime.timedelta(days=_days_since_sunday(christmas) or 7)
    return fourth - datetime.timedelta(weeks=3)


def epiphany(year: int) -> D:
    if not _setting("LITURGY_EPIPHANY_ON_SUNDAY", True):
        return D(year, 1, 6)
    jan2 = D(year, 1, 2)
    return jan2 + datetime.timedelta(days=(6 - jan2.weekday()) % 7)  # dimanche du 2 au 8 janvier


def baptism_of_the_lord(year: int) -> D:
    epi = epiphany(year)
    if epi.weekday() == 6 and epi.day >= 7:
        return epi + DAY  # Épiphanie le 7 ou le 8 : Baptême le lundi
    return epi + datetime.timedelta(days=(6 - epi.weekday()) % 7 or 7)


def holy_family(year: int) -> D:
    """Dimanche dans l'octave de Noël, ou le 30 décembre si Noël est un dimanche."""
    for day in range(26, 32):
        if D(year, 12, day).weekday() == 6:
            return D(year, 12, day)
    return D(year, 12, 30)


def _movable(year: int) -> dict[D, tuple[str, str, str]]:
    """Célébrations mobiles et fixes de l'année civile : date → (libellé, rang, couleur).
    Les dates de ``_proper_days`` sont le propre du jour et l'emportent toujours."""
    e = easter(year)
    ascension = e + datetime.timedelta(days=42 if _setting("LITURGY_ASCENSION_ON_SUNDAY", False) else 39)
    corpus = e + datetime.timedelta(days=63 if _setting("LITURGY_CORPUS_CHRISTI_ON_SUNDAY", True) else 60)
    pentecost = e + datetime.timedelta(days=49)
    ash = e - datetime.timedelta(days=46)
    palm = e - datetime.timedelta(days=7)
    days: dict[D, tuple[str, str, str]] = {
        D(year, 1, 1): ("Sainte Marie, Mère de Dieu", SOLEMNITY, WHITE),
        epiphany(year): ("Épiphanie du Seigneur", SOLEMNITY, WHITE),
        baptism_of_the_lord(year): ("Baptême du Seigneur", LORD_FEAST, WHITE),
        D(year, 2, 2): ("Présentation du Seigneur au Temple", LORD_FEAST, WHITE),
        ash: ("Mercredi des Cendres", WEEKDAY, VIOLET),
        palm: ("Dimanche des Rameaux et de la Passion", SUNDAY, RED),
        e - 3 * DAY: ("Jeudi saint", WEEKDAY, WHITE),
        e - 2 * DAY: ("Vendredi saint", WEEKDAY, RED),
        e - DAY: ("Samedi saint", WEEKDAY, VIOLET),
        e: ("Dimanche de Pâques", SOLEMNITY, WHITE),
        e + 7 * DAY: ("2e dimanche de Pâques, de la divine Miséricorde", SUNDAY, WHITE),
        ascension: ("Ascension du Seigneur", SOLEMNITY, WHITE),
        pentecost: ("Pentecôte", SOLEMNITY, RED),
        e + 56 * DAY: ("Sainte Trinité", SOLEMNITY, WHITE),
        corpus: ("Saint-Sacrement du Corps et du Sang du Christ", SOLEMNITY, WHITE),
        e + 68 * DAY: ("Sacré-Cœur de Jésus", SOLEMNITY, WHITE),
        D(year, 6, 24): ("Nativité de saint Jean-Baptiste", SOLEMNITY, WHITE),
        D(year, 6, 29): ("Saints Pierre et Paul, apôtres", SOLEMNITY, RED),
        D(year, 8, 6): ("Transfiguration du Seigneur", LORD_FEAST, WHITE),
        D(year, 8, 15): ("Assomption de la Vierge Marie", SOLEMNITY, WHITE),
        D(year, 9, 14): ("La Croix glorieuse", LORD_FEAST, RED),
        D(year, 11, 1): ("Tous les Saints", SOLEMNITY, WHITE),
        D(year, 11, 2): ("Commémoraison de tous les fidèles défunts", FEAST, VIOLET),
        D(year, 11, 9): ("Dédicace de la basilique du Latran", LORD_FEAST, WHITE),
        advent_start(year) - 7 * DAY: ("Le Christ, Roi de l'univers", SOLEMNITY, WHITE),
        D(year, 12, 25): ("Nativité du Seigneur", SOLEMNITY, WHITE),
        holy_family(year): ("Sainte Famille de Jésus, Marie et Joseph", LORD_FEAST, WHITE),
    }
    # Solennités transférées (normes universelles) :
    joseph = D(year, 3, 19)
    if palm <= joseph < e:
        joseph = palm - DAY  # semaine sainte : anticipée au samedi précédent
    elif joseph.weekday() == 6:
        joseph += DAY  # dimanche de Carême : lundi
    days[joseph] = ("Saint Joseph, époux de la Vierge Marie", SOLEMNITY, WHITE)
    annunciation = D(year, 3, 25)
    if palm <= annunciation <= e + 7 * DAY:
        annunciation = e + 8 * DAY  # semaine sainte ou octave de Pâques : lundi après la Miséricorde
    elif annunciation.weekday() == 6:
        annunciation += DAY
    days[annunciation] = ("Annonciation du Seigneur", SOLEMNITY, WHITE)
    immaculate = D(year, 12, 8)
    if immaculate.weekday() == 6:
        immaculate += DAY  # dimanche de l'Avent : lundi
    days[immaculate] = ("Immaculée Conception de la Vierge Marie", SOLEMNITY, WHITE)
    return days


def _proper_days(year: int) -> frozenset[D]:
    """Jours dont la célébration EST le propre du temps (cycles de Noël et de Pâques)."""
    e = easter(year)
    ascension = e + datetime.timedelta(days=42 if _setting("LITURGY_ASCENSION_ON_SUNDAY", False) else 39)
    corpus = e + datetime.timedelta(days=63 if _setting("LITURGY_CORPUS_CHRISTI_ON_SUNDAY", True) else 60)
    offsets = (-46, -7, -3, -2, -1, 0, 7, 49, 56, 68)
    return frozenset(
        [e + datetime.timedelta(days=o) for o in offsets]
        + [ascension, corpus, epiphany(year), baptism_of_the_lord(year), holy_family(year)]
        + [advent_start(year) - 7 * DAY, D(year, 11, 2)]
    )


# Sanctoral du calendrier romain général : fêtes et mémoires OBLIGATOIRES à date fixe
# (mois, jour) → (libellé, rang, couleur). Les mémoires facultatives et les calendriers
# propres (diocèse, pays) ne sont pas couverts. Une fête/mémoire ne s'applique qu'à une
# férie (jamais un dimanche, une solennité ou une fête du Seigneur déjà posée) et hors
# Carême/Triduum/octave de Pâques (RG liturgique : mémoires alors facultatives ou omises).
_SANCTORAL: dict[tuple[int, int], tuple[str, str, str]] = {
    (1, 2): ("Saints Basile le Grand et Grégoire de Nazianze", MEMORIAL, WHITE),
    (1, 17): ("Saint Antoine, abbé", MEMORIAL, WHITE),
    (1, 21): ("Sainte Agnès, vierge et martyre", MEMORIAL, RED),
    (1, 24): ("Saint François de Sales", MEMORIAL, WHITE),
    (1, 25): ("Conversion de saint Paul, apôtre", FEAST, WHITE),
    (1, 26): ("Saints Timothée et Tite", MEMORIAL, WHITE),
    (1, 28): ("Saint Thomas d'Aquin", MEMORIAL, WHITE),
    (1, 31): ("Saint Jean Bosco", MEMORIAL, WHITE),
    (2, 10): ("Sainte Scholastique, vierge", MEMORIAL, WHITE),
    (2, 22): ("Chaire de saint Pierre, apôtre", FEAST, WHITE),
    (4, 25): ("Saint Marc, évangéliste", FEAST, RED),
    (4, 29): ("Sainte Catherine de Sienne, vierge et docteur de l'Église", MEMORIAL, WHITE),
    (5, 3): ("Saints Philippe et Jacques, apôtres", FEAST, RED),
    (5, 14): ("Saint Matthias, apôtre", FEAST, RED),
    (5, 26): ("Saint Philippe Néri", MEMORIAL, WHITE),
    (5, 31): ("Visitation de la Vierge Marie", FEAST, WHITE),
    (6, 1): ("Saint Justin, martyr", MEMORIAL, RED),
    (6, 3): ("Saints Charles Lwanga et ses compagnons, martyrs", MEMORIAL, RED),
    (6, 5): ("Saint Boniface, évêque et martyr", MEMORIAL, RED),
    (6, 11): ("Saint Barnabé, apôtre", MEMORIAL, RED),
    (6, 13): ("Saint Antoine de Padoue", MEMORIAL, WHITE),
    (6, 21): ("Saint Louis de Gonzague", MEMORIAL, WHITE),
    (6, 28): ("Saint Irénée, évêque et martyr", MEMORIAL, RED),
    (7, 3): ("Saint Thomas, apôtre", FEAST, RED),
    (7, 11): ("Saint Benoît, abbé", MEMORIAL, WHITE),
    (7, 15): ("Saint Bonaventure", MEMORIAL, WHITE),
    (7, 22): ("Sainte Marie Madeleine", FEAST, WHITE),
    (7, 25): ("Saint Jacques, apôtre", FEAST, RED),
    (7, 26): ("Saints Joachim et Anne, parents de la Vierge Marie", MEMORIAL, WHITE),
    (7, 29): ("Saintes Marthe, Marie et saint Lazare", MEMORIAL, WHITE),
    (7, 31): ("Saint Ignace de Loyola", MEMORIAL, WHITE),
    (8, 1): ("Saint Alphonse-Marie de Liguori", MEMORIAL, WHITE),
    (8, 4): ("Saint Jean-Marie Vianney, curé d'Ars", MEMORIAL, WHITE),
    (8, 8): ("Saint Dominique", MEMORIAL, WHITE),
    (8, 10): ("Saint Laurent, diacre et martyr", FEAST, RED),
    (8, 11): ("Sainte Claire, vierge", MEMORIAL, WHITE),
    (8, 14): ("Saint Maximilien-Marie Kolbe, martyr", MEMORIAL, RED),
    (8, 20): ("Saint Bernard", MEMORIAL, WHITE),
    (8, 21): ("Saint Pie X", MEMORIAL, WHITE),
    (8, 22): ("Vierge Marie Reine", MEMORIAL, WHITE),
    (8, 24): ("Saint Barthélemy, apôtre", FEAST, RED),
    (8, 27): ("Sainte Monique", MEMORIAL, WHITE),
    (8, 28): ("Saint Augustin", MEMORIAL, WHITE),
    (8, 29): ("Martyre de saint Jean-Baptiste", MEMORIAL, RED),
    (9, 3): ("Saint Grégoire le Grand", MEMORIAL, WHITE),
    (9, 8): ("Nativité de la Vierge Marie", FEAST, WHITE),
    (9, 13): ("Saint Jean Chrysostome", MEMORIAL, WHITE),
    (9, 15): ("Notre-Dame des Douleurs", MEMORIAL, WHITE),
    (9, 16): ("Saints Corneille, pape, et Cyprien, évêque, martyrs", MEMORIAL, RED),
    (9, 21): ("Saint Matthieu, apôtre et évangéliste", FEAST, RED),
    (9, 27): ("Saint Vincent de Paul", MEMORIAL, WHITE),
    (9, 29): ("Saints Michel, Gabriel et Raphaël, archanges", FEAST, WHITE),
    (9, 30): ("Saint Jérôme", MEMORIAL, WHITE),
    (10, 1): ("Sainte Thérèse de l'Enfant-Jésus, vierge et docteur de l'Église", MEMORIAL, WHITE),
    (10, 2): ("Saints Anges gardiens", MEMORIAL, WHITE),
    (10, 4): ("Saint François d'Assise", MEMORIAL, WHITE),
    (10, 7): ("Notre-Dame du Rosaire", MEMORIAL, WHITE),
    (10, 15): ("Sainte Thérèse d'Avila, vierge et docteur de l'Église", MEMORIAL, WHITE),
    (10, 17): ("Saint Ignace d'Antioche, évêque et martyr", MEMORIAL, RED),
    (10, 18): ("Saint Luc, évangéliste", FEAST, RED),
    (10, 28): ("Saints Simon et Jude, apôtres", FEAST, RED),
    (11, 10): ("Saint Léon le Grand", MEMORIAL, WHITE),
    (11, 11): ("Saint Martin de Tours", MEMORIAL, WHITE),
    (11, 12): ("Saint Josaphat, évêque et martyr", MEMORIAL, RED),
    (11, 17): ("Sainte Élisabeth de Hongrie", MEMORIAL, WHITE),
    (11, 21): ("Présentation de la Vierge Marie", MEMORIAL, WHITE),
    (11, 22): ("Sainte Cécile, vierge et martyre", MEMORIAL, RED),
    (11, 24): ("Saints André Dung-Lac et ses compagnons, martyrs", MEMORIAL, RED),
    (11, 30): ("Saint André, apôtre", FEAST, RED),
    (12, 3): ("Saint François Xavier", MEMORIAL, WHITE),
    (12, 7): ("Saint Ambroise", MEMORIAL, WHITE),
    (12, 13): ("Sainte Lucie, vierge et martyre", MEMORIAL, RED),
    (12, 14): ("Saint Jean de la Croix", MEMORIAL, WHITE),
    (12, 26): ("Saint Étienne, premier martyr", FEAST, RED),
    (12, 27): ("Saint Jean, apôtre et évangéliste", FEAST, WHITE),
    (12, 28): ("Saints Innocents, martyrs", FEAST, RED),
}


def _sanctoral_for(day: D) -> tuple[str, str, str] | None:
    return _SANCTORAL.get((day.month, day.day))


def _ordinal(n: int, *, feminine: bool = False) -> str:
    if n == 1:
        return "1re" if feminine else "1er"
    return f"{n}e"


def _season_and_week(day: D) -> tuple[str, int | None]:
    year = day.year
    e = easter(year)
    ash = e - datetime.timedelta(days=46)
    pentecost = e + datetime.timedelta(days=49)
    advent = advent_start(year)
    if day >= advent and day < D(year, 12, 25):
        return ADVENT, (day - advent).days // 7 + 1
    if day >= D(year, 12, 25) or day <= baptism_of_the_lord(year):
        return CHRISTMAS, None
    if day < ash:
        baptism = baptism_of_the_lord(year)
        anchor = baptism - datetime.timedelta(days=_days_since_sunday(baptism))
        return ORDINARY, (day - anchor).days // 7 + 1
    if day < e - 3 * DAY:
        lent1 = ash + 4 * DAY
        return LENT, 0 if day < lent1 else (day - lent1).days // 7 + 1
    if day < e:
        return TRIDUUM, None
    if day <= pentecost:
        return EASTER, (day - e).days // 7 + 1
    christ_king = advent - 7 * DAY
    sunday = day - datetime.timedelta(days=_days_since_sunday(day))
    return ORDINARY, 34 - (christ_king - sunday).days // 7


def _default_label(day: D, season: str, week: int | None) -> str:
    if season in (CHRISTMAS, TRIDUUM) or week is None:
        return f"{WEEKDAYS[day.weekday()]} du {SEASON_LABELS[season].lower()}"
    if season == LENT and week == 0:
        return f"{WEEKDAYS[day.weekday()]} après les Cendres"
    if day.weekday() == 6:
        return f"{_ordinal(week)} dimanche {SEASON_OF[season]}"
    return f"{WEEKDAYS[day.weekday()]} de la {_ordinal(week, feminine=True)} semaine {SEASON_OF[season]}"


def _season_color(day: D, season: str, week: int | None) -> str:
    if season in (ADVENT, LENT):
        if day.weekday() == 6 and ((season == ADVENT and week == 3) or (season == LENT and week == 4)):
            return ROSE  # Gaudete, Laetare
        return VIOLET
    if season in (CHRISTMAS, EASTER):
        return WHITE
    if season == TRIDUUM:
        return RED
    return GREEN


def _overrides_sunday(rank: str, season: str) -> bool:
    """Les dimanches de l'Avent, du Carême et de Pâques l'emportent sur tout ; ailleurs,
    les solennités et les fêtes du Seigneur remplacent le dimanche."""
    if season in (ADVENT, LENT, EASTER):
        return False
    return rank in (SOLEMNITY, LORD_FEAST)


def liturgical_day(day: D) -> LiturgicalDay:
    season, week = _season_and_week(day)
    liturgical_year = day.year + 1 if day >= advent_start(day.year) else day.year
    label, rank, color = (
        _default_label(day, season, week),
        SUNDAY if day.weekday() == 6 else WEEKDAY,
        _season_color(day, season, week),
    )
    special = _movable(day.year).get(day)
    if special is not None and (
        day.weekday() != 6 or day in _proper_days(day.year) or _overrides_sunday(special[1], season)
    ):
        label, rank, color = special
    elif special is None and rank == WEEKDAY:
        # Fêtes et mémoires du sanctoral : n'écrasent qu'une férie, hors Carême/Triduum et
        # hors octave de Pâques (où les mémoires sont facultatives ou omises).
        e = easter(day.year)
        in_easter_octave = e < day < e + 8 * DAY
        if season not in (LENT, TRIDUUM) and not in_easter_octave:
            sanctoral = _sanctoral_for(day)
            if sanctoral is not None:
                label, rank, color = sanctoral
    return LiturgicalDay(
        date=day,
        liturgical_year=liturgical_year,
        season=season,
        season_label=SEASON_LABELS[season],
        week=week,
        celebration=label,
        rank=rank,
        color=color,
        sunday_cycle={0: "C", 1: "A", 2: "B"}[liturgical_year % 3],
        weekday_cycle="I" if liturgical_year % 2 else "II",
    )
