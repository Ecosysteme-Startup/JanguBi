"""Présence dans la messagerie : « en ligne » et « vu à » (plan V2 §4, lot B2).

Principe :
- chaque connexion WebSocket authentifiée (conversation ou notifications) incrémente un
  compteur par personne dans le cache (Redis en production), clé à durée de vie courte
  (``PRESENCE_TTL_SECONDS``, 60 s) rafraîchie par le battement du client
  (``{"type": "presence.ping"}`` toutes les 25 s) ;
- le passage de 0 à 1 connexion (« en ligne ») et de 1 à 0 (« hors ligne », « vu à » écrit
  en base) est diffusé en ``presence.changed`` aux seuls interlocuteurs : les personnes avec
  qui l'on a une conversation, hors blocage ;
- la présence n'est visible que si la personne l'a choisi (``montrer_presence``) ; par
  défaut, oui pour le clergé et le staff, non pour les fidèles.

Une connexion coupée sans fermeture propre (processus tué) laisse le compteur trop haut au
plus ``PRESENCE_TTL_SECONDS`` : sans battement, la clé expire et la personne redevient
hors ligne pour les lectures (l'événement « hors ligne » n'est alors pas diffusé).
"""

import datetime
import logging
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.cache import caches
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.hierarchy.enums import DegreOrdre
from apps.messaging.models import Conversation, MessageBlock
from apps.users.models import BaseUser

logger = logging.getLogger(__name__)

PRESENCE_EVENT = "presence.changed"


def _cache() -> Any:
    return caches[settings.PRESENCE_CACHE_ALIAS]


def _key(user_id: Any) -> str:
    return f"presence:conn:{user_id}"


def _ttl() -> int:
    return settings.PRESENCE_TTL_SECONDS


# --- Réglage « montrer ma présence » -----------------------------------------------------------


def presence_default_for(user: BaseUser) -> bool:
    """Défaut du réglage : oui pour le clergé (ordonné) et le staff (office en cours), non sinon."""
    from apps.hierarchy import authz

    if user.degre_ordre and user.degre_ordre != DegreOrdre.AUCUN:
        return True
    if user.is_staff:
        return True
    return bool(authz.grants(user))


def presence_visible(user: BaseUser) -> bool:
    if user.montrer_presence is not None:
        return bool(user.montrer_presence)
    return presence_default_for(user)


@transaction.atomic
def presence_setting_update(*, user: BaseUser, montrer_presence: bool | None) -> BaseUser:
    """Change le réglage (``None`` : revenir au défaut) et prévient les interlocuteurs."""
    before = presence_visible(user)
    user.montrer_presence = montrer_presence
    user.save(update_fields=["montrer_presence", "updated_at"])
    after = presence_visible(user)
    if before != after:
        transaction.on_commit(lambda: presence_broadcast(user=user, setting_changed=True))
    return user


# --- Interlocuteurs ------------------------------------------------------------------------------


def presence_contacts(*, user: Any) -> set[Any]:
    """Identifiants des interlocuteurs : l'autre participant de chacune de mes conversations,
    sauf blocage dans un sens ou dans l'autre."""
    user_id = getattr(user, "pk", user)
    pairs = Conversation.objects.filter(Q(participant_a_id=user_id) | Q(participant_b_id=user_id)).values_list(
        "participant_a_id", "participant_b_id"
    )
    others = {b if a == user_id else a for a, b in pairs}
    if not others:
        return set()
    blocked = MessageBlock.objects.filter(
        Q(blocker_id=user_id, blocked_id__in=others) | Q(blocked_id=user_id, blocker_id__in=others)
    ).values_list("blocker_id", "blocked_id")
    for blocker, blocked_id in blocked:
        others.discard(blocked_id if blocker == user_id else blocker)
    return others


# --- Compteur de connexions -----------------------------------------------------------------------


def presence_is_online(*, user_id: Any) -> bool:
    return bool(_cache().get(_key(user_id)))


def presence_online_map(*, user_ids: list[Any]) -> dict[Any, bool]:
    values = _cache().get_many([_key(u) for u in user_ids])
    return {u: bool(values.get(_key(u))) for u in user_ids}


def presence_connect(*, user: BaseUser) -> bool:
    """Une connexion de plus. Vrai si la personne vient de passer en ligne (diffusé)."""
    cache, key, ttl = _cache(), _key(user.pk), _ttl()
    if cache.add(key, 1, ttl):
        became_online = True
    else:
        try:
            count = cache.incr(key)
            cache.touch(key, ttl)
            became_online = count <= 1
        except ValueError:  # expirée entre add() et incr()
            cache.add(key, 1, ttl)
            became_online = True
    if became_online:
        presence_broadcast(user=user, online=True)
    return became_online


def presence_heartbeat(*, user: BaseUser) -> bool:
    """Battement du client : prolonge la clé. Si elle avait expiré (réseau coupé plus de 60 s),
    la personne repasse en ligne : vrai dans ce cas (diffusé)."""
    cache, key, ttl = _cache(), _key(user.pk), _ttl()
    if cache.touch(key, ttl):
        return False
    if cache.add(key, 1, ttl):
        presence_broadcast(user=user, online=True)
        return True
    return False


def presence_disconnect(*, user: BaseUser, now: datetime.datetime | None = None) -> bool:
    """Une connexion de moins. À la dernière : « vu à » écrit en base et diffusé. Vrai dans ce cas."""
    cache, key = _cache(), _key(user.pk)
    try:
        remaining = cache.decr(key)
    except ValueError:  # clé expirée : plus aucune connexion connue
        remaining = 0
    if remaining > 0:
        return False
    cache.delete(key)
    seen_at = now or timezone.now()
    BaseUser.objects.filter(pk=user.pk).update(last_seen_at=seen_at)
    user.last_seen_at = seen_at
    presence_broadcast(user=user, online=False)
    return True


# --- Diffusion ----------------------------------------------------------------------------------


def presence_payload(*, user: BaseUser, online: bool | None = None) -> dict[str, Any]:
    """Trame ``presence.changed`` telle que la reçoivent les interlocuteurs. Présence masquée :
    ni « en ligne » ni « vu à »."""
    if not presence_visible(user):
        return {"user_id": str(user.pk), "visible": False, "online": None, "last_seen_at": None}
    if online is None:
        online = presence_is_online(user_id=user.pk)
    last_seen = user.last_seen_at
    return {
        "user_id": str(user.pk),
        "visible": True,
        "online": online,
        "last_seen_at": None if online or last_seen is None else last_seen.isoformat(),
    }


def presence_broadcast(*, user: BaseUser, online: bool | None = None, setting_changed: bool = False) -> int:
    """Diffuse l'état de ``user`` à ses interlocuteurs (groupes ``user_<id>``). Une présence
    masquée n'est diffusée qu'au moment où elle le devient (pour effacer l'affichage) : ses
    connexions et déconnexions ne produisent rien, sinon leur heure se devinerait."""
    if not setting_changed and not presence_visible(user):
        return 0
    layer = get_channel_layer()
    if layer is None:
        return 0
    contacts = presence_contacts(user=user)
    if not contacts:
        return 0
    payload = presence_payload(user=user, online=online)
    message = {"type": "presence.changed", **payload}
    sent = 0
    for contact_id in contacts:
        try:
            async_to_sync(layer.group_send)(f"user_{contact_id}", message)
            sent += 1
        except Exception:  # noqa: BLE001 — un groupe injoignable ne bloque pas les autres
            logger.warning("presence.broadcast_failed", extra={"user_id": str(user.pk)})
    return sent
