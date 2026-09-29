"""Infrastructure SSE (``text/event-stream``) servie par Daphne en ASGI (plan V2 §4, lot B2).

Transport : la couche Channels (Redis en production) ; chaque flux est un groupe
``sse.<flux>``. La publication est synchrone (services, signaux, tâches Celery) ; la
lecture est un générateur asynchrone rendu par ``StreamingHttpResponse``.

Reprise (``Last-Event-ID``) : chaque événement reçoit un numéro croissant par flux et reste
lisible ``SSE_REPLAY_TTL_SECONDS`` dans le cache, une clé par événement (pas de liste à
réécrire, donc pas de course entre deux publications). À la reconnexion, les événements
manqués sont rejoués ; si le trou dépasse ``SSE_REPLAY_SIZE`` ou si un événement a expiré,
le flux envoie l'événement de resynchronisation du flux (le client recharge ses données).

Protocole détaillé pour les clients : docs/TEMPS-REEL.md.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from asgiref.sync import async_to_sync, sync_to_async
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.http import StreamingHttpResponse

logger = logging.getLogger(__name__)

_SEQ_KEY = "sse:seq:{stream}"
_EVENT_KEY = "sse:evt:{stream}:{id}"


def _group(stream: str) -> str:
    return f"sse.{stream}"


def sse_format(*, event: str, data: Any, event_id: int | str | None = None) -> str:
    """Un message SSE. ``data`` est sérialisé en JSON sur une seule ligne."""
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, cls=DjangoJSONEncoder, ensure_ascii=False, separators=(',', ':'))}")
    return "\n".join(lines) + "\n\n"


def _next_id(stream: str) -> int:
    key = _SEQ_KEY.format(stream=stream)
    cache.add(key, 0, None)
    try:
        return int(cache.incr(key))
    except ValueError:  # clé évincée entre add() et incr()
        cache.add(key, 1, None)
        return 1


def _last_id(stream: str) -> int:
    return int(cache.get(_SEQ_KEY.format(stream=stream)) or 0)


def sse_publish(*, stream: str, event: str, data: dict[str, Any]) -> int:
    """Publie ``event`` sur ``stream`` (après la transaction : à appeler depuis ``on_commit``).
    Renvoie le numéro de l'événement. Une panne du transport est journalisée, jamais levée :
    un tableau de bord en retard ne doit pas faire échouer un paiement."""
    try:
        event_id = _next_id(stream)
        record = {"id": event_id, "event": event, "data": data}
        cache.set(_EVENT_KEY.format(stream=stream, id=event_id), record, settings.SSE_REPLAY_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        logger.warning("sse.publish_cache_failed", extra={"stream": stream, "sse_event": event})
        return 0
    layer = get_channel_layer()
    if layer is not None:
        try:
            async_to_sync(layer.group_send)(_group(stream), {"type": "sse.event", **record})
        except Exception:  # noqa: BLE001
            logger.warning("sse.publish_layer_failed", extra={"stream": stream, "sse_event": event})
    return event_id


def sse_replay(*, stream: str, last_event_id: str | None) -> tuple[list[dict[str, Any]], bool]:
    """Événements postérieurs à ``last_event_id`` et indicateur « trou » (resynchronisation)."""
    if not last_event_id:
        return [], False
    try:
        last = int(last_event_id)
    except (TypeError, ValueError):
        return [], True
    current = _last_id(stream)
    if last >= current:
        return [], last > current  # numéro inconnu (cache vidé) : resynchroniser
    if current - last > settings.SSE_REPLAY_SIZE:
        return [], True
    keys = [_EVENT_KEY.format(stream=stream, id=i) for i in range(last + 1, current + 1)]
    found = cache.get_many(keys)
    records = [found[k] for k in keys if k in found]
    return records, len(records) != len(keys)


async def sse_stream(
    *,
    stream: str,
    last_event_id: str | None = None,
    resync: Callable[[], tuple[str, dict[str, Any]]] | None = None,
    heartbeat: float | None = None,
    max_seconds: float | None = None,
) -> AsyncIterator[str]:
    """Générateur du flux : ``retry:``, rejeu éventuel, puis événements en direct avec un
    commentaire de battement (``: ping``) toutes les ``heartbeat`` secondes."""
    heartbeat = settings.SSE_HEARTBEAT_SECONDS if heartbeat is None else heartbeat
    max_seconds = settings.SSE_MAX_CONNECTION_SECONDS if max_seconds is None else max_seconds
    layer = get_channel_layer()
    if layer is None:
        yield ": temps réel indisponible\n\n"
        return
    channel = await layer.new_channel(prefix="sse.")
    group = _group(stream)
    await layer.group_add(group, channel)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def pump() -> None:
        while True:
            await queue.put(await layer.receive(channel))

    pump_task = asyncio.create_task(pump())
    try:
        yield f"retry: {settings.SSE_RETRY_MILLISECONDS}\n: flux {stream}\n\n"
        records, gap = await sync_to_async(sse_replay)(stream=stream, last_event_id=last_event_id)
        sent_up_to = 0
        for record in records:
            sent_up_to = record["id"]
            yield sse_format(event=record["event"], data=record["data"], event_id=record["id"])
        if gap and resync is not None:
            event, data = resync()
            yield sse_format(event=event, data=data, event_id=await sync_to_async(_last_id)(stream))
        deadline = time.monotonic() + max_seconds
        while time.monotonic() < deadline:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=heartbeat)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if message.get("id", 0) <= sent_up_to:
                continue  # déjà rejoué
            yield sse_format(event=message["event"], data=message["data"], event_id=message["id"])
    finally:
        pump_task.cancel()
        try:
            await layer.group_discard(group, channel)
        except Exception:  # noqa: BLE001
            logger.warning("sse.discard_failed", extra={"stream": stream})


def sse_release_db_connection() -> None:
    """Rend la connexion Postgres avant de diffuser : sinon chaque flux ouvert (jusqu'à 30 min)
    garderait une connexion inactive jusqu'à la fin de la requête. Sans effet dans un bloc
    atomique (la vue du flux est hors ATOMIC_REQUESTS ; les tests, eux, sont dans une transaction)."""
    if not connection.in_atomic_block:
        connection.close()


def sse_response(stream: AsyncIterator[str]) -> StreamingHttpResponse:
    """Réponse ``text/event-stream`` sans tampon (Traefik transmet au fil de l'eau ; l'en-tête
    ``X-Accel-Buffering`` couvre un éventuel nginx)."""
    response = StreamingHttpResponse(stream, content_type="text/event-stream; charset=utf-8")
    response["Cache-Control"] = "no-cache, no-transform"
    response["X-Accel-Buffering"] = "no"
    return response
