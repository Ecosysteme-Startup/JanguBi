"""Lecture de la présence : limitée aux interlocuteurs de la personne qui demande."""

from typing import Any

from apps.messaging.services_presence import (
    presence_contacts,
    presence_masked,
    presence_online_map,
    presence_visible,
)
from apps.users.models import BaseUser


def presence_for(*, viewer: BaseUser, user_ids: list[Any]) -> list[dict[str, Any]]:
    """État de présence des ``user_ids`` qui sont des interlocuteurs de ``viewer``.

    Les autres identifiants sont ignorés sans le dire (on ne confirme même pas qu'ils
    existent). Une présence masquée est rendue sans « en ligne » ni « vu à ».

    Réciprocité (décision 2 du 29/09/2026) : qui masque explicitement sa présence ne voit plus
    celle des autres ; toutes ses lignes sont « inconnues » (``visible: false``)."""
    contacts = {str(c) for c in presence_contacts(user=viewer)}
    wanted = [u for u in dict.fromkeys(str(u) for u in user_ids) if u in contacts]
    if not wanted:
        return []
    if presence_masked(viewer):
        return [{"user_id": u, "visible": False, "online": None, "last_seen_at": None} for u in wanted]
    users = list(
        BaseUser.objects.filter(pk__in=wanted, is_active=True).only(
            "pk", "is_staff", "degre_ordre", "montrer_presence", "last_seen_at"
        )
    )
    online = presence_online_map(user_ids=[u.pk for u in users])
    rows = []
    for user in users:
        if not presence_visible(user):
            rows.append({"user_id": user.pk, "visible": False, "online": None, "last_seen_at": None})
            continue
        is_online = online[user.pk]
        rows.append(
            {
                "user_id": user.pk,
                "visible": True,
                "online": is_online,
                "last_seen_at": None if is_online else user.last_seen_at,
            }
        )
    order = {u: i for i, u in enumerate(wanted)}
    return sorted(rows, key=lambda r: order[str(r["user_id"])])
