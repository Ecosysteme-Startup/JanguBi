"""Calcul pur de la semaine (EF-HIE-05) : aucune base."""

from dataclasses import dataclass
from datetime import date, time

from apps.hierarchy.week import compute_week

MONDAY = date(2026, 9, 28)
SUNDAY = date(2026, 10, 4)


@dataclass
class S:
    weekday: int
    start_time: time
    kind: str = "messe"
    place_id: int = 1
    end_time: time | None = None
    language: str = "fr"
    note: str = ""
    valid_from: date | None = None
    valid_to: date | None = None


@dataclass
class E:
    date: date
    cancelled: bool
    start_time: time | None = None
    kind: str = "messe"
    place_id: int = 1
    end_time: time | None = None
    note: str = ""


def _times(occurrences):
    return [(o.date, o.start_time) for o in occurrences]


def test_recurring_schedules_are_expanded_over_the_week():
    week = compute_week(start=MONDAY, schedules=[S(0, time(7)), S(6, time(9, 30))], exceptions=[])
    assert _times(week) == [(MONDAY, time(7)), (SUNDAY, time(9, 30))]


def test_cancellation_with_time_removes_only_that_mass():
    schedules = [S(6, time(7, 30)), S(6, time(9, 30))]
    week = compute_week(start=MONDAY, schedules=schedules, exceptions=[E(SUNDAY, True, time(7, 30))])
    assert _times(week) == [(SUNDAY, time(9, 30))]


def test_cancellation_without_time_removes_all_of_that_kind_that_day():
    schedules = [S(6, time(7, 30)), S(6, time(9, 30)), S(6, time(16), kind="confession")]
    week = compute_week(start=MONDAY, schedules=schedules, exceptions=[E(SUNDAY, True)])
    assert [(o.kind, o.start_time) for o in week] == [("confession", time(16))]


def test_extra_schedule_is_added_and_flagged():
    week = compute_week(start=MONDAY, schedules=[], exceptions=[E(date(2026, 10, 1), False, time(19), note="Veillée")])
    assert len(week) == 1
    assert week[0].is_exception and week[0].note == "Veillée"


def test_exceptions_outside_the_window_are_ignored():
    week = compute_week(start=MONDAY, schedules=[S(0, time(7))], exceptions=[E(date(2026, 10, 5), True)])
    assert _times(week) == [(MONDAY, time(7))]


def test_validity_period_is_respected():
    schedules = [S(0, time(7), valid_to=date(2026, 9, 27)), S(1, time(7), valid_from=date(2026, 9, 29))]
    week = compute_week(start=MONDAY, schedules=schedules, exceptions=[])
    assert _times(week) == [(date(2026, 9, 29), time(7))]


def test_cancellation_is_scoped_to_its_place():
    schedules = [S(6, time(9, 30), place_id=1), S(6, time(9, 30), place_id=2)]
    week = compute_week(start=MONDAY, schedules=schedules, exceptions=[E(SUNDAY, True, place_id=2)])
    assert [o.place_id for o in week] == [1]
