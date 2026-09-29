"""Sonothèque : toutes les lectures (plan suite V2, §5). Aucune écriture.

Le catalogue (pages de source, d'album) est mis en cache 10 minutes par niveau d'accès (public,
membre, gestion), invalidé à chaque publication ou modification (``services.catalog_invalidate``).
"""

import base64
import binascii
import datetime
import json
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank, TrigramWordSimilarity
from django.core.cache import cache
from django.db.models import F, FloatField, Q, QuerySet
from django.db.models.functions import Cast
from django.utils import timezone

from apps.audio import access, signing, storage
from apps.audio.enums import ReportStatus, TrackStatus
from apps.audio.models import (
    Album,
    AudioSource,
    Like,
    ListenerSettings,
    PlaybackPosition,
    PlaybackState,
    Playlist,
    Track,
    TrackNeighbor,
    TrackReport,
    UserRecommendation,
)
from apps.audio.recommendations import current_season, season_reason, user_reco_cache_key
from apps.audio.services import catalog_version, hls_prefix
from apps.core.exceptions import ApplicationError, ConflictError, NotFoundError

RESUME_END_MARGIN_SECONDS = 5  # au-delà, la piste est finie : on repart du début


def catalog_cached(parts: tuple[Any, ...], builder: Callable[[], Any]) -> Any:
    key = "audio:cat:" + ":".join(str(p) for p in (catalog_version(), *parts))
    return cache.get_or_set(key, builder, settings.AUDIO_CATALOG_CACHE_SECONDS)


# --- Objets unitaires ------------------------------------------------------------------------


def source_get(*, source_id: Any) -> AudioSource:
    source = AudioSource.objects.select_related("node", "node__type", "cover").filter(pk=source_id).first()
    if source is None:
        raise NotFoundError("Source introuvable.", code="source_introuvable")
    return source


def album_get(*, album_id: Any) -> Album:
    album = Album.objects.select_related("source__node", "cover").filter(pk=album_id).first()
    if album is None:
        raise NotFoundError("Album introuvable.", code="album_introuvable")
    return album


def track_get(*, track_id: Any) -> Track:
    track = Track.objects.select_related("source__node", "album", "raw_file").filter(pk=track_id).first()
    if track is None:
        raise NotFoundError("Cette piste est introuvable.", code="piste_introuvable")
    return track


def playlist_get(*, playlist_id: Any) -> Playlist:
    playlist = Playlist.objects.select_related("source__node", "owner").filter(pk=playlist_id).first()
    if playlist is None:
        raise NotFoundError("Playlist introuvable.", code="playlist_introuvable")
    return playlist


def report_get(*, report_id: Any) -> TrackReport:
    report = TrackReport.objects.select_related("track__source__node").filter(pk=report_id).first()
    if report is None:
        raise NotFoundError("Signalement introuvable.", code="signalement_introuvable")
    return report


# --- Catalogue -------------------------------------------------------------------------------


def source_list(*, node_id: Any = None, kind: str = "") -> QuerySet[AudioSource]:
    """Toutes les sources actives, par ordre alphabétique : aucun classement entre sources."""
    qs = access.visible_sources().select_related("node", "cover")
    if node_id:
        qs = qs.filter(node_id=node_id)
    if kind:
        qs = qs.filter(kind=kind)
    return qs.order_by("name")


def source_albums(*, user: Any, source: AudioSource) -> QuerySet[Album]:
    return access.visible_albums(access.membership(user)).filter(source=source).order_by("-recorded_on", "-published_at")


def source_top_tracks(*, user: Any, source: AudioSource, limit: int = 10) -> QuerySet[Track]:
    """« Les plus écoutés » **à l'intérieur de cette source** seulement (aucun palmarès entre sources)."""
    return (
        access.listenable_tracks(access.membership(user))
        .filter(source=source)
        .select_related("source", "album")
        .order_by("-play_count", "title")[:limit]
    )


def source_recent_tracks(*, user: Any, source: AudioSource, limit: int = 10) -> QuerySet[Track]:
    return (
        access.listenable_tracks(access.membership(user))
        .filter(source=source)
        .select_related("source", "album")
        .order_by("-published_at")[:limit]
    )


def source_playlists(*, user: Any, source: AudioSource) -> QuerySet[Playlist]:
    return access.visible_editorial_playlists(access.membership(user)).filter(source=source).order_by("title")


def album_list(*, user: Any, source_id: Any = None, kind: str = "") -> QuerySet[Album]:
    qs = access.visible_albums(access.membership(user)).select_related("source", "cover")
    if source_id:
        qs = qs.filter(source_id=source_id)
    if kind:
        qs = qs.filter(kind=kind)
    return qs.order_by("-published_at")


def album_require_visible(*, user: Any, album: Album) -> None:
    if access.can_publish(user, album.source.node):
        return
    if not access.visible_albums(access.membership(user)).filter(pk=album.pk).exists():
        raise NotFoundError("Album introuvable.", code="album_introuvable")


def album_tracks(*, user: Any, album: Album) -> QuerySet[Track]:
    return (
        access.listenable_tracks(access.membership(user))
        .filter(album=album)
        .select_related("source", "album")
        .order_by("position", "created_at")
    )


def playlist_tracks(*, user: Any, playlist: Playlist) -> list[Track]:
    items = playlist.items.select_related("track__source", "track__album").order_by("position")
    allowed = set(
        access.listenable_tracks(access.membership(user))
        .filter(pk__in=[i.track_id for i in items])
        .values_list("pk", flat=True)
    )
    return [i.track for i in items if i.track_id in allowed]


def track_require_visible(*, user: Any, track: Track) -> None:
    access.require_play(user, track)


# --- Recherche -------------------------------------------------------------------------------


def _cursor_decode(cursor: str) -> dict[str, Any]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode() + b"=" * (-len(cursor) % 4)))
        return {"r": float(data["r"]), "p": int(data["p"]), "i": str(data["i"])}
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise ApplicationError("Curseur invalide.", code="curseur_invalide") from exc


def _cursor_encode(rank: float, play_count: int, track_id: Any) -> str:
    raw = json.dumps({"r": rank, "p": play_count, "i": str(track_id)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def track_search(*, user: Any, q: str, cursor: str = "", limit: int = 20) -> dict[str, Any]:
    """Plein texte français sans accents + trigramme sur le titre (fautes de frappe).

    1. filtre de visibilité d'abord (seules les pistes que l'utilisateur peut écouter) ;
    2. classement par pertinence ; 3. puis par popularité **à l'intérieur des résultats** ;
    pagination par curseur (rang, écoutes, id)."""
    q = (q or "").strip()[:200]
    if len(q) < 2:
        raise ApplicationError("Tapez au moins deux caractères.", code="recherche_trop_courte")
    query = SearchQuery(q, config="fr_unaccent", search_type="websearch")
    qs = (
        access.listenable_tracks(access.membership(user))
        .filter(Q(search_vector=query) | Q(title__trigram_similar=q) | Q(title__trigram_word_similar=q))
        .annotate(
            rank=Cast(
                SearchRank(F("search_vector"), query, cover_density=True) + TrigramWordSimilarity(q, "title") * 0.5,
                FloatField(),
            )
        )
        .select_related("source", "album")
    )
    if cursor:
        c = _cursor_decode(cursor)
        qs = qs.filter(
            Q(rank__lt=c["r"]) | Q(rank=c["r"], play_count__lt=c["p"]) | Q(rank=c["r"], play_count=c["p"], pk__gt=c["i"])
        )
    page = list(qs.order_by("-rank", "-play_count", "pk")[: limit + 1])
    has_more = len(page) > limit
    page = page[:limit]
    next_cursor = _cursor_encode(page[-1].rank, page[-1].play_count, page[-1].pk) if has_more and page else None
    return {"results": page, "next_cursor": next_cursor}


# --- Lecture ---------------------------------------------------------------------------------


def stream_urls(*, track: Track, now: datetime.datetime | None = None) -> dict[str, Any]:
    """URL du ``master.m3u8`` (et du MP3 hors ligne) : CDN signé, sinon MinIO présigné, sinon local."""
    now = now or timezone.now()
    ttl = settings.AUDIO_SIGNED_URL_TTL_SECONDS
    prefix = hls_prefix(track.pk, track.encoded_version or 0)
    master_key, mp3_key = f"{prefix}/master.m3u8", f"{prefix}/audio.mp3"
    expires_at = now + datetime.timedelta(seconds=ttl)
    if settings.AUDIO_CDN_BASE_URL:
        master, expires = signing.signed_url(key=master_key, now=now.timestamp(), ttl=ttl)
        mp3, _ = signing.signed_url(key=mp3_key, now=now.timestamp(), ttl=ttl)
        expires_at = datetime.datetime.fromtimestamp(expires, tz=datetime.UTC)
    elif storage.is_s3():
        master = storage.presigned_get(key=master_key, expires_in=ttl)
        mp3 = storage.presigned_get(key=mp3_key, expires_in=ttl)
    else:
        master, mp3 = storage.local_url(key=master_key), storage.local_url(key=mp3_key)
    return {"format": "hls", "master_url": master, "mp3_url": mp3, "expires_at": expires_at}


def resume_position(*, user: Any, track: Track) -> PlaybackPosition | None:
    if not getattr(user, "is_authenticated", False):
        return None
    position = PlaybackPosition.objects.filter(user=user, track=track).first()
    if position is None:
        return None
    if track.duration_seconds and position.position_seconds >= track.duration_seconds - RESUME_END_MARGIN_SECONDS:
        return None
    return position


def playback_info(*, user: Any, track: Track) -> dict[str, Any]:
    """« Qui es-tu, as-tu le droit, où t'es-tu arrêté ? » en un seul aller-retour."""
    access.require_play(user, track)
    if track.status != TrackStatus.PRET or track.encoded_version is None:
        raise ConflictError("Cette piste n'est pas encore prête.", code="piste_pas_prete")
    return {
        "track": track,
        "stream": stream_urls(track=track),
        "resume": resume_position(user=user, track=track),
        "waveform": track.waveform,
    }


def playback_state_get(*, user: Any) -> PlaybackState | None:
    state = PlaybackState.objects.select_related("track__source", "track__album").filter(user=user).first()
    if state is None or not access.can_play(user, state.track):
        return None
    return state


# --- Bibliothèque ----------------------------------------------------------------------------


def library(*, user: Any) -> dict[str, Any]:
    m = access.membership(user)
    listenable = access.listenable_tracks(m)
    liked_ids = list(Like.objects.filter(user=user).order_by("-created_at").values_list("track_id", flat=True)[:200])
    liked = {t.pk: t for t in listenable.filter(pk__in=liked_ids).select_related("source", "album")}
    positions = list(
        PlaybackPosition.objects.filter(user=user).order_by("-client_updated_at").values_list(
            "track_id", "position_seconds", "client_updated_at"
        )[:50]
    )
    recent_tracks = {t.pk: t for t in listenable.filter(pk__in=[p[0] for p in positions]).select_related("source", "album")}
    recent = [
        {"track": recent_tracks[tid], "position_seconds": pos, "updated_at": at}
        for tid, pos, at in positions
        if tid in recent_tracks
    ][:20]
    return {
        "likes": [liked[i] for i in liked_ids if i in liked],
        "playlists": list(Playlist.objects.filter(owner=user).order_by("-updated_at")),
        "recent": recent,
    }


def playlists_of(*, user: Any) -> QuerySet[Playlist]:
    return Playlist.objects.filter(owner=user).order_by("-updated_at")


def liked_track_ids(*, user: Any, track_ids: list[Any]) -> set[Any]:
    if not getattr(user, "is_authenticated", False):
        return set()
    return set(Like.objects.filter(user=user, track_id__in=track_ids).values_list("track_id", flat=True))


def listener_settings_get(*, user: Any) -> ListenerSettings:
    return ListenerSettings.objects.filter(user=user).first() or ListenerSettings(user=user)


# --- Recommandations -------------------------------------------------------------------------


def _cold_start(*, user: Any, limit: int = 30) -> list[dict[str, Any]]:
    """Nouveautés de sa paroisse, puis playlists éditoriales, puis le temps liturgique."""
    from apps.audio.recommendations import _parish_sources

    m = access.membership(user)
    listenable = access.listenable_tracks(m).select_related("source", "album")
    out: list[dict[str, Any]] = []
    seen: set[Any] = set()

    def push(track: Track, reason: str) -> None:
        if track.pk not in seen and len(out) < limit:
            seen.add(track.pk)
            out.append({"track": track, "reason": reason})

    sources = _parish_sources(user) if getattr(user, "is_authenticated", False) else []
    for track in listenable.filter(source__in=sources).order_by("-published_at")[:limit]:
        push(track, f"Nouveauté de {track.source.name}")
    playlists = access.visible_editorial_playlists(m).select_related("source").order_by("-published_at")[:5]
    for playlist in playlists:
        for track in playlist_tracks(user=user, playlist=playlist)[:5]:
            push(track, f"Sélection de {playlist.source.name if playlist.source else ''} : {playlist.title}")
    season = current_season()
    for track in listenable.filter(Q(liturgical_season=season) | Q(album__liturgical_season=season)).order_by(
        "-published_at"
    )[:limit]:
        push(track, season_reason(season))
    return out


def recommendations_for(*, user: Any) -> dict[str, Any]:
    enabled = settings.AUDIO_RECO_ENABLED and listener_settings_get(user=user).recommendations_enabled
    if not enabled:
        return {"personnalise": False, "demarrage_a_froid": True, "results": _cold_start(user=user)}
    key = user_reco_cache_key(user.pk)
    rows = cache.get(key)
    if rows is None:
        rows = [
            (str(t), reason)
            for t, reason in UserRecommendation.objects.filter(user=user)
            .order_by("-score")
            .values_list("track_id", "reason")[: settings.AUDIO_RECO_PER_USER]
        ]
        cache.set(key, rows, 26 * 3600)
    if rows:
        tracks = {
            str(t.pk): t
            for t in access.listenable_tracks(access.membership(user))
            .filter(pk__in=[r[0] for r in rows])
            .select_related("source", "album")
        }
        results = [{"track": tracks[t], "reason": reason} for t, reason in rows if t in tracks]
        if results:
            return {"personnalise": True, "demarrage_a_froid": False, "results": results}
    return {"personnalise": True, "demarrage_a_froid": True, "results": _cold_start(user=user)}


def next_tracks(*, user: Any, track: Track, limit: int = 10) -> list[Track]:
    """« À écouter ensuite » : voisins précalculés (co-écoute puis contenu), filtrés par droits ;
    à défaut, la suite de l'album puis les pistes les plus écoutées de la même source."""
    access.require_play(user, track)
    listenable = access.listenable_tracks(access.membership(user)).exclude(pk=track.pk)
    neighbor_ids = [
        n
        for n in TrackNeighbor.objects.filter(track=track)
        .order_by("method", "-score")  # « coecoute » < « contenu » : la co-écoute d'abord
        .values_list("neighbor_id", flat=True)
    ]
    ordered = list(dict.fromkeys(neighbor_ids))
    allowed = {t.pk: t for t in listenable.filter(pk__in=ordered).select_related("source", "album")}
    result = [allowed[i] for i in ordered if i in allowed]
    if len(result) < limit and track.album_id:
        for t in listenable.filter(album_id=track.album_id, position__gt=track.position).order_by("position")[:limit]:
            if t not in result:
                result.append(t)
    if len(result) < limit:
        for t in listenable.filter(source_id=track.source_id).order_by("-play_count", "title")[: limit * 2]:
            if t not in result:
                result.append(t)
    return result[:limit]


# --- Staff -----------------------------------------------------------------------------------


def staff_tracks(*, user: Any, source: AudioSource, status: str = "") -> QuerySet[Track]:
    access.require_publish(user, source.node)
    qs = Track.objects.filter(source=source).select_related("source", "album").order_by("-created_at")
    if status:
        qs = qs.filter(status=status)
    return qs


def staff_sources(*, user: Any) -> QuerySet[AudioSource]:
    m = access.membership(user)
    condition = Q(pk__in=[])
    for path, inherits in m.publish_scopes:
        condition |= Q(node__path__startswith=path) if inherits else Q(node__path=path)
    return AudioSource.objects.filter(condition).select_related("node").order_by("name")


def reports_open(*, user: Any) -> QuerySet[TrackReport]:
    from apps.hierarchy import authz

    nodes = authz.noeuds_autorises(user, access.MODERATE)
    return (
        TrackReport.objects.filter(status=ReportStatus.OUVERT, track__source__node__in=nodes)
        .select_related("track__source")
        .order_by("created_at")
    )
