"""Plage de silence des notifications (EF-PAROI-08) : calcul pur, sans base."""

import datetime


def quiet_until(*, now: datetime.datetime, start: datetime.time, end: datetime.time) -> datetime.datetime | None:
    """Fin de la plage de silence si ``now`` y tombe, sinon ``None``.

    La plage peut chevaucher minuit (22 h → 6 h) ; ``start == end`` = pas de silence.
    """
    if start == end:
        return None
    t = now.timetz().replace(tzinfo=None)
    today_end = now.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if start < end:  # plage dans la journée
        return today_end if start <= t < end else None
    if t >= start:  # soirée : la fin est demain
        return today_end + datetime.timedelta(days=1)
    if t < end:  # petit matin
        return today_end
    return None
