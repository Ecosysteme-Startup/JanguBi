"""Progression d'encodage d'un envoi audio en SSE : ``GET /api/v1/audio/uploads/<id>/flux/``.

Complément du polling de ``GET audio/uploads/<id>/`` (qui reste la référence) : même contenu,
poussé à chaque changement. Un flux par piste (``audio.upload.<track_id>``) ; un seul événement,
``audio.encodage`` :

    {"track_id", "version", "status", "encoding_step", "encoding_percent", "failure_reason", "final"}

``final`` vaut ``true`` quand la piste est ``pret`` ou ``echec`` : le client ferme alors son
``EventSource`` (sinon il se reconnecterait). Ni titre ni nom : identifiants et état seulement.

Publication : par les services de la sonothèque (``apps.audio.services``), après la transaction
(``on_commit``) ou directement depuis le worker pour l'avancement des étapes (écrit hors
transaction). Protocole commun (reprise, battement) : ``apps.realtime.sse`` et docs/TEMPS-REEL.md.
"""

from collections.abc import AsyncIterator
from functools import partial
from typing import Any

from django.db import transaction

from apps.audio import access
from apps.audio.enums import TrackStatus
from apps.audio.models import Track
from apps.core.exceptions import NotFoundError
from apps.realtime.sse import sse_format, sse_publish

EVENT_PROGRESS = "audio.encodage"
FINAL_STATUSES = frozenset({TrackStatus.PRET, TrackStatus.ECHEC})


def stream_for(track_id: Any) -> str:
    return f"audio.upload.{track_id}"


def progress_data(
    *, track_id: Any, version: int, status: str, step: str, percent: int, failure_reason: str = ""
) -> dict[str, Any]:
    return {
        "track_id": str(track_id),
        "version": version,
        "status": status,
        "encoding_step": step,
        "encoding_percent": percent,
        "failure_reason": failure_reason,
        "final": status in FINAL_STATUSES,
    }


def track_progress_data(track: Track) -> dict[str, Any]:
    return progress_data(
        track_id=track.pk,
        version=track.version,
        status=track.status,
        step=track.encoding_step,
        percent=track.encoding_percent,
        failure_reason=track.failure_reason,
    )


def upload_progress_publish(*, track_id: Any, **fields: Any) -> None:
    """Publie tout de suite (hors transaction : avancement écrit par le worker)."""
    sse_publish(stream=stream_for(track_id), event=EVENT_PROGRESS, data=progress_data(track_id=track_id, **fields))


def upload_progress_on_commit(track: Track) -> None:
    """Publie l'état de ``track`` une fois la transaction validée (rien en cas d'annulation)."""
    transaction.on_commit(
        partial(
            upload_progress_publish,
            track_id=track.pk,
            version=track.version,
            status=track.status,
            step=track.encoding_step,
            percent=track.encoding_percent,
            failure_reason=track.failure_reason,
        )
    )


# --- Droits et état courant ---------------------------------------------------------------------


def upload_flux_check(*, user: Any, track: Track) -> None:
    """Mêmes droits que ``GET audio/uploads/<id>/`` : l'auteur de l'envoi, ou ``audio.publier``
    sur le nœud de la source (MFA exigée)."""
    if track.uploaded_by_id != getattr(user, "pk", None):
        access.require_publish(user, track.source.node)


def upload_resync(track_id: Any) -> tuple[str, dict[str, Any]]:
    """État courant, envoyé à l'ouverture du flux et quand la reprise est impossible."""
    track = Track.objects.filter(pk=track_id).first()
    if track is None:
        raise NotFoundError("Envoi introuvable.", code="upload_introuvable")
    return EVENT_PROGRESS, {**track_progress_data(track), "resync": True}


async def upload_stream(*, stream: AsyncIterator[str], snapshot: dict[str, Any] | None) -> AsyncIterator[str]:
    """Enveloppe du flux commun : après l'en-tête ``retry:``, l'état courant (sans ``id:``, pour ne
    pas déplacer le point de reprise) ; puis ferme le flux après un événement final."""
    try:
        async for chunk in stream:
            yield chunk
            if snapshot is not None:
                yield sse_format(event=EVENT_PROGRESS, data=snapshot)
                if snapshot["final"]:
                    return
                snapshot = None
            elif chunk.startswith(("id:", "event:")) and '"final":true' in chunk:
                return
    finally:
        await stream.aclose()  # type: ignore[attr-defined]
