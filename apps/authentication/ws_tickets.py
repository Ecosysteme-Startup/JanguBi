"""Tickets WebSocket à usage unique (60 s).

Le navigateur ne peut pas poser d'en-tête Authorization sur une WebSocket. Plutôt que de
mettre le jeton d'accès (valable sur toute l'API) dans l'URL — où il finit dans les
journaux d'accès et l'historique —, le client échange son jeton contre un ticket court,
à usage unique, qui n'ouvre qu'une socket.
"""

import secrets
from typing import Any

from django.contrib.auth import get_user_model
from django.core.cache import cache

TICKET_TTL_SECONDS = 60
_PREFIX = "ws-ticket:"


def ws_ticket_issue(*, user: Any) -> str:
    ticket = secrets.token_urlsafe(32)
    cache.set(f"{_PREFIX}{ticket}", str(user.pk), TICKET_TTL_SECONDS)
    return ticket


def ws_ticket_consume(*, ticket: str) -> Any | None:
    """Utilisateur actif du ticket, ou ``None`` (inconnu, expiré, déjà utilisé)."""
    if not ticket or len(ticket) > 128:
        return None
    key = f"{_PREFIX}{ticket}"
    user_id = cache.get(key)
    if user_id is None or not cache.delete(key):  # delete() = verrou d'usage unique
        return None
    return get_user_model().objects.filter(pk=user_id, is_active=True).first()
