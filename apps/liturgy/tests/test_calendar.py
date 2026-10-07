"""Calendrier liturgique local (EF-PAR-02) : fonctions pures, sans base."""

import datetime

import pytest

from apps.liturgy import calendar as cal

D = datetime.date


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (2024, D(2024, 3, 31)),
        (2025, D(2025, 4, 20)),
        (2026, D(2026, 4, 5)),
        (2027, D(2027, 3, 28)),
        (2038, D(2038, 4, 25)),
    ],
)
def test_easter(year, expected):
    assert cal.easter(year) == expected


def test_advent_start_and_christ_the_king():
    assert cal.advent_start(2026) == D(2026, 11, 29)
    assert cal.advent_start(2022) == D(2022, 11, 27)  # Noël un dimanche
    assert cal.liturgical_day(D(2026, 11, 22)).celebration == "Le Christ, Roi de l'univers"
    assert cal.liturgical_day(D(2026, 11, 22)).week == 34


def test_movable_feasts_2026():
    assert cal.liturgical_day(D(2026, 2, 18)).celebration == "Mercredi des Cendres"
    assert cal.liturgical_day(D(2026, 3, 29)).color == cal.RED  # Rameaux
    assert cal.liturgical_day(D(2026, 4, 3)).celebration == "Vendredi saint"
    assert cal.liturgical_day(D(2026, 4, 3)).season == cal.TRIDUUM
    easter_day = cal.liturgical_day(D(2026, 4, 5))
    assert (easter_day.celebration, easter_day.color, easter_day.season) == (
        "Dimanche de Pâques",
        cal.WHITE,
        cal.EASTER,
    )
    pentecost = cal.liturgical_day(D(2026, 5, 24))
    assert (pentecost.celebration, pentecost.color) == ("Pentecôte", cal.RED)
    assert cal.liturgical_day(D(2026, 5, 14)).celebration == "Ascension du Seigneur"


def test_seasons_weeks_and_labels():
    assert cal.liturgical_day(D(2026, 2, 17)).celebration == "Mardi de la 6e semaine du temps ordinaire"
    assert cal.liturgical_day(D(2026, 2, 19)).celebration == "Jeudi après les Cendres"
    assert cal.liturgical_day(D(2026, 5, 25)).week == 8  # lundi de Pentecôte : 8e semaine
    assert cal.liturgical_day(D(2026, 10, 4)).celebration == "27e dimanche du temps ordinaire"
    assert cal.liturgical_day(D(2026, 10, 5)).color == cal.GREEN
    assert cal.liturgical_day(D(2026, 12, 6)).celebration == "2e dimanche de l'Avent"
    assert cal.liturgical_day(D(2026, 12, 26)).season == cal.CHRISTMAS


def test_rose_sundays():
    assert cal.liturgical_day(D(2026, 3, 15)).color == cal.ROSE  # Laetare
    assert cal.liturgical_day(D(2026, 12, 13)).color == cal.ROSE  # Gaudete


def test_cycles():
    day = cal.liturgical_day(D(2026, 10, 5))
    assert (day.liturgical_year, day.sunday_cycle, day.weekday_cycle) == (2026, "A", "II")
    advent = cal.liturgical_day(D(2026, 11, 29))
    assert (advent.liturgical_year, advent.sunday_cycle, advent.weekday_cycle) == (2027, "B", "I")


def test_christmas_cycle_and_epiphany_on_sunday():
    assert cal.epiphany(2026) == D(2026, 1, 4)
    assert cal.baptism_of_the_lord(2026) == D(2026, 1, 11)
    assert cal.baptism_of_the_lord(2024) == D(2024, 1, 8)  # Épiphanie le 7 : Baptême le lundi
    assert cal.liturgical_day(D(2026, 1, 11)).celebration == "Baptême du Seigneur"
    assert cal.liturgical_day(D(2026, 1, 12)).celebration == "Lundi de la 1re semaine du temps ordinaire"
    assert cal.holy_family(2022) == D(2022, 12, 30)


def test_epiphany_fixed_when_configured(settings):
    settings.LITURGY_EPIPHANY_ON_SUNDAY = False
    assert cal.epiphany(2026) == D(2026, 1, 6)
    assert cal.liturgical_day(D(2026, 1, 6)).celebration == "Épiphanie du Seigneur"


def test_transferred_solemnities():
    assert cal.liturgical_day(D(2024, 4, 8)).celebration == "Annonciation du Seigneur"  # semaine sainte 2024
    assert cal.liturgical_day(D(2024, 12, 9)).celebration == "Immaculée Conception de la Vierge Marie"
    assert cal.liturgical_day(D(2024, 12, 8)).celebration == "2e dimanche de l'Avent"
    assert cal.liturgical_day(D(2023, 3, 20)).celebration == "Saint Joseph, époux de la Vierge Marie"


def test_solemnity_replaces_ordinary_sunday_but_not_lent_sunday():
    assert cal.liturgical_day(D(2026, 11, 1)).celebration == "Tous les Saints"  # dimanche du T.O.
    assert cal.liturgical_day(D(2026, 3, 22)).celebration == "5e dimanche de Carême"


def test_sanctoral_feasts_and_memorials_2026():
    # JB-WEB-010 : fêtes et mémoires du calendrier romain général, plus en « férie vert ».
    archanges = cal.liturgical_day(D(2026, 9, 29))  # mardi
    assert archanges.celebration == "Saints Michel, Gabriel et Raphaël, archanges"
    assert (archanges.rank, archanges.color) == (cal.FEAST, cal.WHITE)

    therese = cal.liturgical_day(D(2026, 10, 1))  # jeudi
    assert therese.celebration.startswith("Sainte Thérèse de l'Enfant-Jésus")
    assert (therese.rank, therese.color) == (cal.MEMORIAL, cal.WHITE)

    anges = cal.liturgical_day(D(2026, 10, 2))  # vendredi
    assert anges.celebration == "Saints Anges gardiens"
    assert (anges.rank, anges.color) == (cal.MEMORIAL, cal.WHITE)

    # Mémoire de martyre un jour de semaine : couleur rouge.
    agnes = cal.liturgical_day(D(2026, 1, 21))  # mercredi
    assert (agnes.rank, agnes.color) == (cal.MEMORIAL, cal.RED)


def test_sanctoral_never_overrides_sunday_or_season():
    # Saint François d'Assise (4 oct) tombe un dimanche en 2026 : le dimanche l'emporte.
    assert cal.liturgical_day(D(2026, 10, 4)).celebration == "27e dimanche du temps ordinaire"
    # Une férie sans mémoire reste férie verte.
    assert cal.liturgical_day(D(2026, 10, 5)).rank == cal.WEEKDAY
    assert cal.liturgical_day(D(2026, 10, 5)).color == cal.GREEN
