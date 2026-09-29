"""Calcul pur (sans base) de la semaine des horaires d'un ou plusieurs lieux (EF-HIE-05)."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Protocol


class ScheduleLike(Protocol):
    place_id: int
    kind: str
    weekday: int
    start_time: time
    end_time: time | None
    language: str
    note: str
    valid_from: date | None
    valid_to: date | None


class ExceptionLike(Protocol):
    place_id: int
    date: date
    kind: str
    cancelled: bool
    start_time: time | None
    end_time: time | None
    note: str


@dataclass(frozen=True)
class Occurrence:
    place_id: int
    date: date
    kind: str
    start_time: time
    end_time: time | None
    language: str
    note: str
    is_exception: bool


def _is_valid_on(schedule: ScheduleLike, day: date) -> bool:
    if schedule.valid_from is not None and day < schedule.valid_from:
        return False
    return schedule.valid_to is None or day <= schedule.valid_to


def _is_cancelled(occurrence: Occurrence, cancellations: Iterable[ExceptionLike]) -> bool:
    for exc in cancellations:
        if exc.place_id != occurrence.place_id or exc.date != occurrence.date or exc.kind != occurrence.kind:
            continue
        if exc.start_time is None or exc.start_time == occurrence.start_time:
            return True
    return False


def compute_week(
    *, start: date, schedules: Iterable[ScheduleLike], exceptions: Iterable[ExceptionLike], days: int = 7
) -> list[Occurrence]:
    """Occurrences des ``days`` jours à partir de ``start``, exceptions appliquées, triées."""
    schedules = list(schedules)
    exceptions = [e for e in exceptions if start <= e.date < start + timedelta(days=days)]
    cancellations = [e for e in exceptions if e.cancelled]

    occurrences: list[Occurrence] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        for s in schedules:
            if s.weekday != day.weekday() or not _is_valid_on(s, day):
                continue
            occurrence = Occurrence(
                place_id=s.place_id,
                date=day,
                kind=s.kind,
                start_time=s.start_time,
                end_time=s.end_time,
                language=s.language,
                note=s.note,
                is_exception=False,
            )
            if not _is_cancelled(occurrence, cancellations):
                occurrences.append(occurrence)

    for e in exceptions:
        if e.cancelled or e.start_time is None:
            continue
        occurrences.append(
            Occurrence(
                place_id=e.place_id,
                date=e.date,
                kind=e.kind,
                start_time=e.start_time,
                end_time=e.end_time,
                language="",
                note=e.note,
                is_exception=True,
            )
        )

    return sorted(occurrences, key=lambda o: (o.date, o.start_time, o.place_id))
