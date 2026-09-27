"""Sonothèque paroissiale : toutes les écritures (plan suite V2, §5).

Principes :
- les droits se lisent sur le nœud de la source (``audio.publier``, ``audio.moderer``) ;
- l'encodage est idempotent : verrou par piste, ``version`` demandée, dossier HLS versionné et
  immuable ; une tâche livrée deux fois ou périmée ne fait rien ;
- aucune donnée d'écoute dans les logs (loi 2008-12) : seulement des identifiants de piste.
"""

import datetime
import logging
import os
import pathlib
import tempfile
import uuid
from functools import partial
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from apps.audio import access, storage, transcode
from apps.audio.enums import (
    PlayEventKind,
    ReportStatus,
    TrackStatus,
    Visibility,
    most_restrictive,
)
from apps.audio.models import (
    Album,
    AudioSource,
    Like,
    ListenerSettings,
    PlaybackPosition,
    PlaybackState,
    Playlist,
    PlaylistItem,
    Track,
    TrackRendition,
    TrackReport,
)
from apps.core.exceptions import ApplicationError, ConflictError, NotFoundError
from apps.files.models import File
from apps.files.utils import file_generate_name
from apps.hierarchy.audit import audit_log
from apps.hierarchy.models import Node

logger = logging.getLogger(__name__)

TRACK_METADATA_FIELDS = (
    "title",
    "performers",
    "composer",
    "language",
    "liturgical_season",
    "tags",
    "description",
    "visibility",
    "position",
)
ALBUM_FIELDS = ("kind", "title", "description", "visibility", "recorded_on", "liturgical_season", "cover")
SOURCE_FIELDS = ("kind", "name", "description", "cover", "is_active")
PLAYLIST_FIELDS = ("title", "description", "visibility", "cover")

# --- Cache du catalogue ----------------------------------------------------------------------

CATALOG_VERSION_KEY = "audio:catalog:version"


def catalog_version() -> int:
    return int(cache.get_or_set(CATALOG_VERSION_KEY, 1, None) or 1)


def catalog_invalidate() -> None:
    """Invalide tout le catalogue mis en cache (publication, modification, retrait)."""
    try:
        cache.incr(CATALOG_VERSION_KEY)
    except ValueError:
        cache.set(CATALOG_VERSION_KEY, 2, None)


def _on_commit_invalidate() -> None:
    transaction.on_commit(catalog_invalidate)


# --- Index de recherche ----------------------------------------------------------------------

_SEARCH_SQL = """
UPDATE audio_track t SET search_vector =
    setweight(to_tsvector('fr_unaccent', coalesce(t.title, '')), 'A')
    || setweight(to_tsvector('fr_unaccent',
        coalesce((SELECT s.name FROM audio_audiosource s WHERE s.id = t.source_id), '') || ' ' ||
        coalesce((SELECT a.title FROM audio_album a WHERE a.id = t.album_id), '') || ' ' ||
        array_to_string(t.performers, ' ') || ' ' || t.composer), 'B')
    || setweight(to_tsvector('fr_unaccent',
        array_to_string(t.tags, ' ') || ' ' || t.liturgical_season || ' ' || t.description), 'C')
WHERE t.id = ANY(%s::uuid[])
"""


def track_search_index(*, track_ids: list[Any]) -> None:
    """``tsvector`` pondéré (A : titre ; B : source, album, interprètes, compositeur ; C : tags,
    temps liturgique, description), français sans accents."""
    if not track_ids:
        return
    with connection.cursor() as cursor:
        cursor.execute(_SEARCH_SQL, [[str(i) for i in track_ids]])


# --- Sources et albums -----------------------------------------------------------------------


@transaction.atomic
def source_create(
    *, actor: Any, node: Node, kind: str, name: str, description: str = "", cover: File | None = None
) -> AudioSource:
    access.require_publish(actor, node)
    if AudioSource.objects.filter(node=node, name=name).exists():
        raise ConflictError("Une source porte déjà ce nom sur ce nœud.", code="source_existe")
    source = AudioSource.objects.create(
        node=node, kind=kind, name=name, description=description, cover=cover, created_by=actor
    )
    audit_log(actor=actor, action="audio.source.creer", target=source, node=node)
    _on_commit_invalidate()
    return source


@transaction.atomic
def source_update(*, actor: Any, source: AudioSource, data: dict[str, Any]) -> AudioSource:
    access.require_publish(actor, source.node)
    for name in SOURCE_FIELDS:
        if name in data:
            setattr(source, name, data[name])
    source.save()
    if "name" in data:
        track_search_index(track_ids=list(source.tracks.values_list("pk", flat=True)))
    audit_log(actor=actor, action="audio.source.modifier", target=source, node=source.node)
    _on_commit_invalidate()
    return source


def _tracks_effective_visibility_refresh(*, album: Album) -> None:
    for track in album.tracks.all():
        effective = most_restrictive(track.visibility, album.visibility)
        if track.effective_visibility != effective:
            track.effective_visibility = effective
            track.save(update_fields=["effective_visibility", "updated_at"])


@transaction.atomic
def album_create(*, actor: Any, source: AudioSource, title: str, **fields: Any) -> Album:
    access.require_publish(actor, source.node)
    album = Album.objects.create(
        source=source, title=title, created_by=actor, **{k: v for k, v in fields.items() if k in ALBUM_FIELDS}
    )
    audit_log(actor=actor, action="audio.album.creer", target=album, node=source.node)
    return album


@transaction.atomic
def album_update(*, actor: Any, album: Album, data: dict[str, Any]) -> Album:
    access.require_publish(actor, album.source.node)
    for name in ALBUM_FIELDS:
        if name in data:
            setattr(album, name, data[name])
    album.save()
    if "visibility" in data:
        _tracks_effective_visibility_refresh(album=album)
    if "title" in data:
        track_search_index(track_ids=list(album.tracks.values_list("pk", flat=True)))
    _on_commit_invalidate()
    return album


@transaction.atomic
def album_publish(*, actor: Any, album: Album) -> Album:
    """Publie l'album et ses pistes prêtes qui ne l'étaient pas encore."""
    access.require_publish(actor, album.source.node)
    now = timezone.now()
    if album.published_at is None:
        album.published_at = now
        album.save(update_fields=["published_at", "updated_at"])
    for track in album.tracks.filter(status=TrackStatus.PRET, published_at__isnull=True):
        track.published_at = now
        track.save(update_fields=["published_at", "updated_at"])
    audit_log(actor=actor, action="audio.album.publier", target=album, node=album.source.node)
    _on_commit_invalidate()
    return album


# --- Upload ----------------------------------------------------------------------------------


def validate_audio_type(*, file_name: str, file_type: str) -> tuple[str, str]:
    """Extension, type MIME et cohérence des deux (même logique que ``apps.files``, liste audio)."""
    extension = pathlib.Path(file_name or "").suffix.lower()
    normalized = (file_type or "").split(";")[0].strip().lower()
    allowed = settings.AUDIO_UPLOAD_ALLOWED_TYPES
    if not extension or extension not in {e for exts in allowed.values() for e in exts}:
        raise ApplicationError(
            "Format non accepté. Formats possibles : mp3, m4a, aac, wav, flac, ogg, opus.", code="format_audio"
        )
    if normalized not in allowed:
        raise ApplicationError(f"Type de fichier non accepté : « {normalized or '?'} ».", code="format_audio")
    if extension not in allowed[normalized]:
        raise ApplicationError(
            f"L'extension « {extension} » ne correspond pas au type « {normalized} ».", code="format_audio"
        )
    return extension, normalized


def _check_size(size: int) -> None:
    if size <= 0:
        raise ApplicationError("Le fichier est vide.", code="fichier_vide")
    if size > settings.AUDIO_UPLOAD_MAX_SIZE:
        mo = settings.AUDIO_UPLOAD_MAX_SIZE // (1024 * 1024)
        raise ApplicationError(f"Fichier trop volumineux (maximum {mo} Mo).", code="fichier_trop_gros")


@transaction.atomic
def upload_start(
    *,
    actor: Any,
    source: AudioSource,
    file_name: str,
    file_type: str,
    file_size: int,
    rights_confirmed: bool,
    album: Album | None = None,
    title: str = "",
    visibility: str = Visibility.PUBLIC,
) -> dict[str, Any]:
    """Crée la piste (``brouillon``) et renvoie le POST présigné vers ``audio-raw/`` (bucket privé)."""
    access.require_publish(actor, source.node)
    if not rights_confirmed:
        raise ApplicationError(
            "Cochez « J'ai les droits sur cet enregistrement » pour continuer.", code="droits_non_confirmes"
        )
    if album is not None and album.source_id != source.pk:
        raise ApplicationError("Cet album appartient à une autre source.", code="album_autre_source")
    _, content_type = validate_audio_type(file_name=file_name, file_type=file_type)
    _check_size(file_size)

    stored_name = file_generate_name(file_name)
    key = f"{settings.AUDIO_RAW_PREFIX}/{stored_name}"
    raw = File(
        original_file_name=file_name[:500],
        file_name=stored_name,
        file_type=content_type,
        uploaded_by=actor,
    )
    raw.file.name = key
    raw.save()

    position = (album.tracks.count() + 1) if album is not None else 0
    track = Track.objects.create(
        source=source,
        album=album,
        position=position,
        title=(title or pathlib.Path(file_name).stem)[:250],
        visibility=visibility,
        effective_visibility=most_restrictive(visibility, album.visibility) if album else visibility,
        status=TrackStatus.BROUILLON,
        raw_file=raw,
        rights_confirmed_at=timezone.now(),
        uploaded_by=actor,
    )
    track_search_index(track_ids=[track.pk])
    audit_log(
        actor=actor, action="audio.piste.televerser", target=track, node=source.node, metadata={"droits": True}
    )

    if storage.is_s3():
        presigned = storage.presigned_post(
            key=key,
            content_type=content_type,
            max_size=settings.AUDIO_UPLOAD_MAX_SIZE,
            expires_in=settings.AUDIO_UPLOAD_PRESIGNED_EXPIRY,
        )
        target = {"method": "POST", "url": presigned["url"], "fields": presigned["fields"]}
    else:
        from django.urls import reverse

        path = reverse("api:audio:upload-local", kwargs={"track_id": track.pk})
        target = {"method": "POST", "url": f"{settings.APP_DOMAIN}{path}", "fields": {}}
    return {
        "upload_id": track.pk,
        "track": track,
        "max_size": settings.AUDIO_UPLOAD_MAX_SIZE,
        "expires_in": settings.AUDIO_UPLOAD_PRESIGNED_EXPIRY,
        **target,
    }


def _require_uploader(actor: Any, track: Track) -> None:
    if track.uploaded_by_id != getattr(actor, "pk", None) and not access.can_publish(actor, track.source.node):
        raise NotFoundError("Envoi introuvable.", code="upload_introuvable")


@transaction.atomic
def upload_local(*, actor: Any, track: Track, file_obj: Any) -> Track:
    """Développement sans S3 : le client envoie le fichier ici au lieu du POST présigné."""
    if storage.is_s3():
        raise ApplicationError("En stockage S3, envoyez le fichier avec le POST présigné.", code="upload_s3")
    _require_uploader(actor, track)
    if track.status != TrackStatus.BROUILLON or track.raw_file is None:
        raise ConflictError("Ce fichier a déjà été reçu.", code="upload_deja_termine")
    _check_size(file_obj.size)
    key = track.raw_file.file.name
    if default_storage.exists(key):
        default_storage.delete(key)
    default_storage.save(key, file_obj)
    return track


def _enqueue_transcode(track: Track) -> None:
    from apps.audio.tasks import audio_transcode_task

    track_id, version = str(track.pk), track.version
    transaction.on_commit(lambda: audio_transcode_task.delay(track_id, version))


@transaction.atomic
def upload_finish(*, actor: Any, track: Track) -> Track:
    """Le client a téléversé : on vérifie l'objet, la piste passe ``en_file`` et part à l'encodage.
    Idempotent : un second appel renvoie l'état courant sans relancer l'encodage."""
    track = Track.objects.select_for_update(of=("self",)).select_related("raw_file", "source__node").get(pk=track.pk)
    _require_uploader(actor, track)
    if track.status != TrackStatus.BROUILLON:
        return track
    raw = track.raw_file
    if raw is None:
        raise ApplicationError("Aucun fichier attendu pour cette piste.", code="upload_sans_fichier")
    info = storage.head(key=raw.file.name)
    if info is None:
        raise ApplicationError("Le fichier n'est pas encore arrivé. Réessayez dans un instant.", code="upload_absent")
    if info["size"] > settings.AUDIO_UPLOAD_MAX_SIZE:
        raise ApplicationError("Fichier trop volumineux (maximum 500 Mo).", code="fichier_trop_gros")
    raw.upload_finished_at = timezone.now()
    raw.save(update_fields=["upload_finished_at", "updated_at"])
    track.version += 1
    track.status = TrackStatus.EN_FILE
    track.failure_reason = ""
    track.save(update_fields=["version", "status", "failure_reason", "updated_at"])
    _enqueue_transcode(track)
    return track


@transaction.atomic
def track_reencode(*, actor: Any, track: Track) -> Track:
    """Nouvel encodage depuis le fichier source gardé dans ``audio-raw`` (nouvelle version)."""
    track = Track.objects.select_for_update(of=("self",)).select_related("raw_file", "source__node").get(pk=track.pk)
    access.require_publish(actor, track.source.node)
    if track.raw_file is None or not track.raw_file.is_valid:
        raise ApplicationError("Le fichier source n'est pas disponible.", code="source_absente")
    if track.status in (TrackStatus.EN_FILE, TrackStatus.ENCODAGE):
        return track
    track.version += 1
    track.status = TrackStatus.EN_FILE
    track.failure_reason = ""
    track.save(update_fields=["version", "status", "failure_reason", "updated_at"])
    _enqueue_transcode(track)
    return track


# --- Encodage --------------------------------------------------------------------------------


def _lock_key(track_id: Any) -> str:
    return f"audio:transcode-lock:{track_id}"


def hls_prefix(track_id: Any, version: int) -> str:
    return f"{settings.AUDIO_HLS_PREFIX}/{track_id}/{version}"


def _notify_uploader(track: Track, *, event_type: str) -> None:
    if track.uploaded_by_id is None:
        return
    from apps.messaging.services_notifications import people_notify

    people_notify(
        user_ids=[track.uploaded_by_id],
        topic=None,
        event_type=event_type,
        payload={
            "track_id": str(track.pk),
            "title": track.title,
            "status": track.status,
            "failure_reason": track.failure_reason,
        },
    )


@transaction.atomic
def _mark_failed(*, track_id: Any, version: int, reason: str) -> None:
    track = Track.objects.select_for_update().filter(pk=track_id).first()
    if track is None or track.version != version:
        return
    track.status = TrackStatus.ECHEC
    track.failure_reason = reason[:1000]
    track.save(update_fields=["status", "failure_reason", "updated_at"])
    _notify_uploader(track, event_type="audio.encodage_echec")


@transaction.atomic
def _mark_retrying(*, track_id: Any, version: int, reason: str) -> None:
    Track.objects.filter(pk=track_id, version=version, status=TrackStatus.ENCODAGE).update(
        status=TrackStatus.EN_FILE, failure_reason=reason[:1000], updated_at=timezone.now()
    )


@transaction.atomic
def _mark_ready(*, track_id: Any, version: int, result: transcode.TranscodeResult, prefix: str) -> str:
    track = Track.objects.select_for_update().get(pk=track_id)
    if track.version != version:
        return "perime"  # une nouvelle version a été demandée pendant l'encodage
    TrackRendition.objects.filter(track=track, version=version).delete()
    renditions = [
        TrackRendition(
            track=track,
            version=version,
            kind=r.spec.kind,
            codec=r.spec.codec_label,
            bitrate_kbps=r.spec.bitrate_kbps,
            channels=r.spec.channels,
            path=f"{prefix}/{r.playlist}",
            size_bytes=r.size_bytes,
        )
        for r in result.renditions
    ]
    renditions.append(
        TrackRendition(
            track=track, version=version, kind="mp3", codec="MP3", bitrate_kbps=128, channels=2,
            path=f"{prefix}/{result.mp3}", size_bytes=result.mp3_size,
        )  # fmt: skip
    )
    TrackRendition.objects.bulk_create(renditions)
    track.status = TrackStatus.PRET
    track.failure_reason = ""
    track.encoded_version = version
    track.encoded_at = timezone.now()
    track.duration_seconds = result.duration_seconds
    track.probe_tags = result.tags
    track.waveform = result.waveform
    track.save()
    _notify_uploader(track, event_type="audio.encodage_termine")
    if track.published_at is not None:
        _on_commit_invalidate()
    return "pret"


def transcode_track(*, track_id: Any, version: int, final_attempt: bool = True) -> str:
    """Encode la version ``version`` de la piste. Renvoie l'issue : ``pret``, ``echec``,
    ``deja_fait``, ``perime``, ``verrouille`` ou ``introuvable``.

    Idempotent : un verrou par piste (Redis, 30 min) empêche deux workers d'encoder en même temps ;
    une version déjà encodée ou dépassée est ignorée. Une erreur technique est relancée pour que la
    tâche réessaie (3 fois), sauf à la dernière tentative où la piste passe en ``echec``.
    """
    token = uuid.uuid4().hex
    lock = _lock_key(track_id)
    if not cache.add(lock, token, settings.AUDIO_TRANSCODE_LOCK_SECONDS):
        return "verrouille"
    prefix = hls_prefix(track_id, version)
    try:
        with transaction.atomic():
            track = Track.objects.select_for_update(of=("self",)).select_related("raw_file").filter(pk=track_id).first()
            if track is None:
                return "introuvable"
            if track.version != version:
                return "perime"
            if track.status == TrackStatus.PRET and track.encoded_version == version:
                return "deja_fait"
            raw = track.raw_file
            if raw is None or not raw.is_valid:
                track.status = TrackStatus.ECHEC
                track.failure_reason = "Fichier source absent."
                track.save(update_fields=["status", "failure_reason", "updated_at"])
                _notify_uploader(track, event_type="audio.encodage_echec")
                return "echec"
            track.status = TrackStatus.ENCODAGE
            track.encoding_started_at = timezone.now()
            track.encode_attempts = F("encode_attempts") + 1
            track.save(update_fields=["status", "encoding_started_at", "encode_attempts", "updated_at"])
            raw_key = raw.file.name
            title, artist = track.title, ", ".join(track.performers)

        try:
            with tempfile.TemporaryDirectory(prefix="jangubi-audio-") as tmp:
                src = os.path.join(tmp, "source" + pathlib.Path(raw_key).suffix.lower())
                out, work = os.path.join(tmp, "out"), os.path.join(tmp, "work")
                os.makedirs(out)
                os.makedirs(work)
                storage.download(key=raw_key, local_path=src)
                result = transcode.transcode(src, out, work_dir=work, title=title, artist=artist)
                for rel in result.files:  # master.m3u8 en dernier : la version n'est lisible qu'une fois complète
                    storage.put_file(key=f"{prefix}/{rel}", local_path=os.path.join(out, rel))
        except transcode.InvalidMediaError as exc:
            logger.info("audio.transcode.invalid", extra={"track_id": str(track_id), "version": version})
            _mark_failed(track_id=track_id, version=version, reason=str(exc))
            return "echec"
        except Exception as exc:  # noqa: BLE001 - erreur technique : on réessaie
            logger.warning("audio.transcode.error", extra={"track_id": str(track_id), "version": version})
            try:
                storage.delete_prefix(prefix=prefix + "/")
            except Exception:  # noqa: BLE001
                pass
            reason = f"Erreur d'encodage : {exc}"[:500]
            if final_attempt:
                _mark_failed(track_id=track_id, version=version, reason=reason)
                return "echec"
            _mark_retrying(track_id=track_id, version=version, reason=reason)
            raise
        return _mark_ready(track_id=track_id, version=version, result=result, prefix=prefix)
    finally:
        if cache.get(lock) == token:
            cache.delete(lock)


# --- Métadonnées et publication d'une piste ----------------------------------------------------


@transaction.atomic
def track_update(*, actor: Any, track: Track, data: dict[str, Any]) -> Track:
    access.require_publish(actor, track.source.node)
    if "album" in data:
        album = data["album"]
        if album is not None and album.source_id != track.source_id:
            raise ApplicationError("Cet album appartient à une autre source.", code="album_autre_source")
        track.album = album
    for name in TRACK_METADATA_FIELDS:
        if name in data:
            setattr(track, name, data[name])
    track.effective_visibility = (
        most_restrictive(track.visibility, track.album.visibility) if track.album else track.visibility
    )
    track.save()
    track_search_index(track_ids=[track.pk])
    _on_commit_invalidate()
    return track


@transaction.atomic
def track_publish(*, actor: Any, track: Track) -> Track:
    access.require_publish(actor, track.source.node)
    if track.status != TrackStatus.PRET:
        raise ConflictError("La piste n'est pas encore prête (encodage).", code="piste_pas_prete")
    if track.published_at is None:
        track.published_at = timezone.now()
        track.save(update_fields=["published_at", "updated_at"])
    audit_log(actor=actor, action="audio.piste.publier", target=track, node=track.source.node)
    _on_commit_invalidate()
    return track


@transaction.atomic
def track_unpublish(*, actor: Any, track: Track) -> Track:
    access.require_publish(actor, track.source.node)
    track.published_at = None
    track.save(update_fields=["published_at", "updated_at"])
    audit_log(actor=actor, action="audio.piste.depublier", target=track, node=track.source.node)
    _on_commit_invalidate()
    return track


# --- Reprise et synchronisation multi-appareils ------------------------------------------------


def _bounded(client_ts: datetime.datetime, now: datetime.datetime) -> datetime.datetime:
    """Horodatage client borné par l'heure serveur : jamais dans le futur, au plus 24 h en arrière."""
    floor = now - datetime.timedelta(seconds=settings.AUDIO_PLAYBACK_MAX_CLIENT_LAG_SECONDS)
    return max(min(client_ts, now), floor)


def _playback_push(user_id: Any, payload: dict[str, Any]) -> None:
    """Événement ``playback.state`` dans le groupe ``user_<id>``. Enveloppe ``notification.push``
    pour que le ``NotificationConsumer`` existant le relaie tel quel (``event_type``) sans créer de
    notification en base."""
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            f"user_{user_id}", {"type": "notification.push", "event_type": "playback.state", **payload}
        )
    except Exception:  # noqa: BLE001 - une socket fermée ne bloque pas l'écriture
        logger.warning("audio.playback.ws_push_failed")


@transaction.atomic
def playback_state_update(
    *,
    user: Any,
    track: Track,
    position_seconds: float,
    device_id: str,
    client_updated_at: datetime.datetime,
    now: datetime.datetime | None = None,
) -> tuple[PlaybackState, bool]:
    """Dernière écriture gagnante. Renvoie l'état courant et ``True`` si cette écriture a gagné."""
    access.require_play(user, track)
    now = now or timezone.now()
    stamp = _bounded(client_updated_at, now)
    position = max(0.0, float(position_seconds))
    if track.duration_seconds:
        position = min(position, float(track.duration_seconds))

    current = PlaybackPosition.objects.select_for_update().filter(user=user, track=track).first()
    if current is None:
        PlaybackPosition.objects.create(
            user=user, track=track, position_seconds=position, device_id=device_id, client_updated_at=stamp
        )
    elif stamp >= current.client_updated_at:
        current.position_seconds, current.device_id, current.client_updated_at = position, device_id, stamp
        current.save()

    state = PlaybackState.objects.select_for_update().filter(user=user).first()
    if state is not None and stamp < state.client_updated_at:
        return state, False
    if state is None:
        state = PlaybackState(user=user)
    state.track, state.position_seconds, state.device_id, state.client_updated_at = track, position, device_id, stamp
    state.save()
    payload = {
        "track_id": str(track.pk),
        "position_seconds": position,
        "device_id": device_id,
        "updated_at": stamp.isoformat(),
    }
    transaction.on_commit(partial(_playback_push, user.pk, payload))
    return state, True


# --- Likes, playlists, réglages ----------------------------------------------------------------


@transaction.atomic
def like_add(*, user: Any, track: Track) -> bool:
    access.require_play(user, track)
    _, created = Like.objects.get_or_create(user=user, track=track)
    if created:
        Track.objects.filter(pk=track.pk).update(like_count=F("like_count") + 1)
    return created


@transaction.atomic
def like_remove(*, user: Any, track: Track) -> bool:
    deleted, _ = Like.objects.filter(user=user, track=track).delete()
    if deleted:
        Track.objects.filter(pk=track.pk, like_count__gt=0).update(like_count=F("like_count") - 1)
    return bool(deleted)


def _require_playlist_editor(actor: Any, playlist: Playlist) -> None:
    if playlist.owner_id is not None:
        if playlist.owner_id != getattr(actor, "pk", None):
            raise NotFoundError("Playlist introuvable.", code="playlist_introuvable")
        return
    assert playlist.source is not None
    access.require_publish(actor, playlist.source.node)


@transaction.atomic
def playlist_create(
    *, actor: Any, title: str, source: AudioSource | None = None, **fields: Any
) -> Playlist:
    """Playlist du fidèle, ou éditoriale si ``source`` est donnée (``audio.publier`` requis)."""
    data = {k: v for k, v in fields.items() if k in PLAYLIST_FIELDS}
    if source is not None:
        access.require_publish(actor, source.node)
        playlist = Playlist.objects.create(source=source, title=title, **data)
        _on_commit_invalidate()
        return playlist
    if data.get("visibility") == Visibility.PAROISSE:
        raise ApplicationError("Une playlist personnelle est privée ou publique.", code="visibilite_invalide")
    return Playlist.objects.create(owner=actor, title=title, **data)


@transaction.atomic
def playlist_update(*, actor: Any, playlist: Playlist, data: dict[str, Any]) -> Playlist:
    _require_playlist_editor(actor, playlist)
    if playlist.owner_id is not None and data.get("visibility") == Visibility.PAROISSE:
        raise ApplicationError("Une playlist personnelle est privée ou publique.", code="visibilite_invalide")
    for name in PLAYLIST_FIELDS:
        if name in data:
            setattr(playlist, name, data[name])
    if playlist.source_id is not None and "published" in data:
        playlist.published_at = timezone.now() if data["published"] else None
    playlist.save()
    if playlist.source_id is not None:
        _on_commit_invalidate()
    return playlist


@transaction.atomic
def playlist_delete(*, actor: Any, playlist: Playlist) -> None:
    _require_playlist_editor(actor, playlist)
    editorial = playlist.source_id is not None
    playlist.delete()
    if editorial:
        _on_commit_invalidate()


@transaction.atomic
def playlist_add_track(*, actor: Any, playlist: Playlist, track: Track) -> PlaylistItem:
    _require_playlist_editor(actor, playlist)
    access.require_play(actor, track)
    existing = PlaylistItem.objects.filter(playlist=playlist, track=track).first()
    if existing is not None:
        return existing
    Playlist.objects.select_for_update().filter(pk=playlist.pk).first()
    last = playlist.items.order_by("-position").values_list("position", flat=True).first()
    item = PlaylistItem.objects.create(playlist=playlist, track=track, position=(last or 0) + 1)
    playlist.save(update_fields=["updated_at"])
    return item


@transaction.atomic
def playlist_remove_track(*, actor: Any, playlist: Playlist, track: Track) -> None:
    _require_playlist_editor(actor, playlist)
    PlaylistItem.objects.filter(playlist=playlist, track=track).delete()
    playlist.save(update_fields=["updated_at"])


@transaction.atomic
def playlist_reorder(*, actor: Any, playlist: Playlist, track_ids: list[Any]) -> Playlist:
    """Nouvel ordre complet : ``track_ids`` doit contenir exactement les pistes de la playlist."""
    _require_playlist_editor(actor, playlist)
    items = {str(i.track_id): i for i in playlist.items.select_for_update()}
    wanted = [str(t) for t in track_ids]
    if sorted(wanted) != sorted(items):
        raise ApplicationError("L'ordre doit reprendre exactement les pistes de la playlist.", code="ordre_invalide")
    for position, track_id in enumerate(wanted, start=1):
        items[track_id].position = position
    PlaylistItem.objects.bulk_update(list(items.values()), ["position"])
    playlist.save(update_fields=["updated_at"])
    return playlist


@transaction.atomic
def listener_settings_update(*, user: Any, recommendations_enabled: bool) -> ListenerSettings:
    prefs, _ = ListenerSettings.objects.get_or_create(user=user)
    prefs.recommendations_enabled = recommendations_enabled
    prefs.save()
    if not recommendations_enabled:
        from apps.audio.models import UserRecommendation
        from apps.audio.recommendations import user_reco_cache_key

        UserRecommendation.objects.filter(user=user).delete()
        transaction.on_commit(lambda: cache.delete(user_reco_cache_key(user.pk)))
    return prefs


# --- Événements d'écoute (table partitionnée) ------------------------------------------------

_INSERT_EVENTS = """
INSERT INTO audio_play_event
    (occurred_at, received_at, client_event_id, user_id, track_id, kind, position_seconds, device_id)
VALUES {values}
ON CONFLICT (client_event_id, occurred_at) DO NOTHING
RETURNING track_id, kind
"""


@transaction.atomic
def play_events_ingest(*, user: Any, events: list[dict[str, Any]], now: datetime.datetime | None = None) -> dict[str, int]:
    """Enregistre un lot d'événements. Idempotent par ``client_event_id`` (+ ``occurred_at``, que le
    client renvoie à l'identique) : une reprise réseau ne compte pas deux fois.

    Rejetés : piste inconnue ou non autorisée, horodatage trop ancien (7 jours) ou dans le futur."""
    now = now or timezone.now()
    oldest = now - datetime.timedelta(days=settings.AUDIO_EVENTS_MAX_AGE_DAYS)
    newest = now + datetime.timedelta(seconds=settings.AUDIO_EVENTS_MAX_FUTURE_SECONDS)
    track_ids = {str(e["track_id"]) for e in events}
    tracks = {str(t.pk): t for t in Track.objects.filter(pk__in=track_ids).select_related("source__node")}
    allowed = {tid for tid, t in tracks.items() if access.can_play(user, t)}
    user_id = user.pk if getattr(user, "is_authenticated", False) else None

    rows: list[Any] = []
    seen: set[tuple[str, datetime.datetime]] = set()
    rejected = 0
    for e in events:
        key = (str(e["client_event_id"]), e["occurred_at"])
        if str(e["track_id"]) not in allowed or not (oldest <= e["occurred_at"] <= newest):
            rejected += 1
            continue
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            (
                e["occurred_at"], now, str(e["client_event_id"]), user_id, str(e["track_id"]),
                e["kind"], float(e.get("position_seconds") or 0), (e.get("device_id") or "")[:100],
            )  # fmt: skip
        )
    inserted: list[tuple[Any, str]] = []
    if rows:
        values = ", ".join(["(%s, %s, %s, %s, %s, %s, %s, %s)"] * len(rows))
        with connection.cursor() as cursor:
            cursor.execute(_INSERT_EVENTS.format(values=values), [v for row in rows for v in row])
            inserted = cursor.fetchall()
    starts: dict[str, int] = {}
    for track_id, kind in inserted:
        if kind == PlayEventKind.START:
            starts[str(track_id)] = starts.get(str(track_id), 0) + 1
    for track_id, count in starts.items():
        Track.objects.filter(pk=track_id).update(play_count=F("play_count") + count)
    return {
        "recus": len(events),
        "enregistres": len(inserted),
        "doublons": len(events) - rejected - len(inserted),
        "rejetes": rejected,
    }


def _month_start(day: datetime.date, shift: int = 0) -> datetime.date:
    index = day.year * 12 + (day.month - 1) + shift
    return datetime.date(index // 12, index % 12 + 1, 1)


def play_event_partitions_ensure(*, today: datetime.date | None = None) -> dict[str, list[str]]:
    """Crée les partitions du mois courant et des ``AUDIO_EVENTS_PARTITIONS_AHEAD`` suivants, et
    supprime celles de plus de ``AUDIO_EVENTS_RETENTION_MONTHS`` mois. Idempotente.

    Si des lignes du mois sont tombées dans la partition ``DEFAULT`` (tâche en retard), elles sont
    déplacées dans la nouvelle partition, dans la même transaction."""
    today = today or timezone.localdate()
    created: list[str] = []
    dropped: list[str] = []
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
            "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'audio_play_event'"
        )
        existing = {row[0] for row in cursor.fetchall()}
        for shift in range(0, settings.AUDIO_EVENTS_PARTITIONS_AHEAD + 1):
            start, end = _month_start(today, shift), _month_start(today, shift + 1)
            name = f"audio_play_event_p{start:%Y%m}"
            if name in existing:
                continue
            cursor.execute(
                "CREATE TEMP TABLE _audio_moved ON COMMIT DROP AS "
                "WITH moved AS (DELETE FROM audio_play_event_default WHERE occurred_at >= %s AND occurred_at < %s "
                "RETURNING *) SELECT * FROM moved",
                [start, end],
            )
            cursor.execute(
                f'CREATE TABLE "{name}" PARTITION OF audio_play_event FOR VALUES FROM (%s) TO (%s)', [start, end]
            )
            cursor.execute(
                "INSERT INTO audio_play_event (id, occurred_at, received_at, client_event_id, user_id, track_id, kind, "
                "position_seconds, device_id) SELECT id, occurred_at, received_at, client_event_id, user_id, track_id, "
                "kind, position_seconds, device_id FROM _audio_moved"
            )
            cursor.execute("DROP TABLE _audio_moved")
            created.append(name)
        cutoff = _month_start(today, -settings.AUDIO_EVENTS_RETENTION_MONTHS)
        for name in sorted(existing):
            suffix = name.removeprefix("audio_play_event_p")
            if len(suffix) == 6 and suffix.isdigit():
                start = datetime.date(int(suffix[:4]), int(suffix[4:]), 1)
                if start < cutoff:
                    cursor.execute(f'DROP TABLE "{name}"')
                    dropped.append(name)
        cursor.execute("DELETE FROM audio_play_event_default WHERE occurred_at < %s", [cutoff])
    return {"creees": created, "supprimees": dropped}


# --- Signalements et modération --------------------------------------------------------------


@transaction.atomic
def report_create(*, user: Any, track: Track, reason: str, comment: str = "") -> TrackReport:
    access.require_play(user, track)
    return TrackReport.objects.create(track=track, reporter=user, reason=reason, comment=comment[:2000])


@transaction.atomic
def report_handle(*, actor: Any, report: TrackReport, decision: str) -> TrackReport:
    """``retire`` : la piste disparaît du catalogue (``hidden_at``) ; ``rejete`` : sans suite."""
    track = report.track
    access.require_moderate(actor, track.source.node)
    if report.status != ReportStatus.OUVERT:
        raise ConflictError("Ce signalement a déjà été traité.", code="signalement_traite")
    if decision not in (ReportStatus.RETIRE, ReportStatus.REJETE):
        raise ApplicationError("Décision inconnue.", code="decision_invalide")
    now = timezone.now()
    TrackReport.objects.filter(track=track, status=ReportStatus.OUVERT).update(
        status=decision, handled_by=actor, handled_at=now, updated_at=now
    )
    if decision == ReportStatus.RETIRE:
        track.hidden_at = now
        track.save(update_fields=["hidden_at", "updated_at"])
        _on_commit_invalidate()
    audit_log(
        actor=actor, action=f"audio.signalement.{decision}", target=track, node=track.source.node,
        metadata={"signalement": report.pk},
    )  # fmt: skip
    report.refresh_from_db()
    return report

