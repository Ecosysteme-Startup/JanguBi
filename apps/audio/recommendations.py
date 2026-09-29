"""Recommandations de la sonothèque, précalculées chaque nuit (plan suite V2, §5.5).

1. **Item → item par co-écoute** : cosinus sur la matrice binaire utilisateur × piste des
   90 derniers jours (écoutes complètes, likes, ajouts en playlist), calculé en SQL ; 50 voisins
   par piste au plus, avec au moins ``AUDIO_RECO_MIN_CO_LISTENERS`` auditeurs communs.
2. **Contenu** : embedding des métadonnées (même fournisseur que les versets, 768 dimensions,
   pgvector) ; sert aux pistes neuves sans historique.
3. **Utilisateur → pistes** : voisins de ses écoutes et likes récents (pondérés par la récence),
   nouveautés de sa paroisse, temps liturgique ; on retire ce qu'il a déjà écouté ou passé ; 100
   au plus, en table et en cache Redis, chacune avec une explication lisible.

Garde-fous : aucune donnée sensible (dons, confessions, messagerie) ; interrupteur global
``AUDIO_RECO_ENABLED`` ; réglage par personne (``ListenerSettings.recommendations_enabled``).
"""

import datetime
import hashlib
import logging
from collections import defaultdict
from typing import Any

import numpy as np
from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from pgvector.django import CosineDistance

from apps.audio import access
from apps.audio.enums import LiturgicalSeason, NeighborMethod, TrackStatus
from apps.audio.models import (
    AudioSource,
    ListenerSettings,
    Track,
    TrackNeighbor,
    UserRecommendation,
)

logger = logging.getLogger(__name__)

CONTENT_WEIGHT = 0.6  # un voisin de contenu compte moins qu'un voisin de co-écoute
PARISH_BONUS = 0.3
SEASON_BONUS = 0.2
RECENCY_HALF_LIFE_DAYS = 30
NEW_DAYS = 60
EMBED_BATCH = 64
USER_RECO_CACHE_SECONDS = 26 * 3600


def user_reco_cache_key(user_id: Any) -> str:
    return f"audio:reco:v1:{user_id}"


def embedding_provider() -> Any:
    """Même fournisseur que les versets (apps/bible) : ``EMBEDDING_PROVIDER`` (stub en test)."""
    from apps.bible.services.embedding_service import _build_provider

    return _build_provider(getattr(settings, "EMBEDDING_PROVIDER", "stub"))


def current_season(day: datetime.date | None = None) -> str:
    from apps.liturgy.calendar import liturgical_day

    return liturgical_day(day or timezone.localdate()).season


def season_reason(season: str) -> str:
    label = LiturgicalSeason(season).label if season in LiturgicalSeason.values else "temps liturgique"
    return f"Pour le {label[0].lower()}{label[1:]}" if label.startswith("Temps") else f"Pour le {label}"


# --- 1. Co-écoute ----------------------------------------------------------------------------

_POSITIVE_SQL = """
    SELECT DISTINCT e.user_id, e.track_id
    FROM audio_play_event e JOIN audio_track t ON t.id = e.track_id
    WHERE e.occurred_at >= %(since)s AND e.user_id IS NOT NULL
      AND (e.kind = 'complete'
           OR (e.kind = 'progress' AND t.duration_seconds > 0
               AND e.position_seconds >= %(ratio)s * t.duration_seconds))
    UNION
    SELECT l.user_id, l.track_id FROM audio_like l WHERE l.created_at >= %(since)s
    UNION
    SELECT p.owner_id, i.track_id
    FROM audio_playlistitem i JOIN audio_playlist p ON p.id = i.playlist_id
    WHERE p.owner_id IS NOT NULL AND i.added_at >= %(since)s
"""

_COLISTEN_SQL = f"""
WITH pos AS ({_POSITIVE_SQL}),
n AS (SELECT track_id, count(*)::float AS c FROM pos GROUP BY track_id),
co AS (
    SELECT a.track_id AS t1, b.track_id AS t2, count(*)::float AS c
    FROM pos a JOIN pos b ON a.user_id = b.user_id AND a.track_id <> b.track_id
    GROUP BY a.track_id, b.track_id
    HAVING count(*) >= %(min_co)s
),
scored AS (
    SELECT co.t1, co.t2, co.c / sqrt(n1.c * n2.c) AS score,
           row_number() OVER (PARTITION BY co.t1 ORDER BY co.c / sqrt(n1.c * n2.c) DESC, co.t2) AS rk
    FROM co JOIN n n1 ON n1.track_id = co.t1 JOIN n n2 ON n2.track_id = co.t2
)
INSERT INTO audio_trackneighbor (track_id, neighbor_id, score, method, computed_at)
SELECT t1, t2, score, 'coecoute', %(now)s FROM scored WHERE rk <= %(top)s
"""


@transaction.atomic
def colisten_neighbors_compute(*, now: datetime.datetime | None = None) -> int:
    now = now or timezone.now()
    params = {
        "since": now - datetime.timedelta(days=settings.AUDIO_RECO_WINDOW_DAYS),
        "ratio": settings.AUDIO_RECO_COMPLETE_RATIO,
        "min_co": settings.AUDIO_RECO_MIN_CO_LISTENERS,
        "now": now,
        "top": settings.AUDIO_RECO_NEIGHBORS,
    }
    TrackNeighbor.objects.filter(method=NeighborMethod.COECOUTE).delete()
    with connection.cursor() as cursor:
        cursor.execute(_COLISTEN_SQL, params)
        return cursor.rowcount


# --- 2. Contenu ------------------------------------------------------------------------------


def embedding_text(track: Track) -> str:
    parts = [
        track.title,
        track.source.name,
        track.album.title if track.album else "",
        ", ".join(track.performers),
        track.composer,
        LiturgicalSeason(track.liturgical_season).label if track.liturgical_season else "",
        " ".join(track.tags),
        track.description[:1000],
    ]
    return ". ".join(p for p in parts if p)


def track_embeddings_refresh(*, provider: Any = None) -> int:
    """Calcule l'embedding des pistes prêtes dont les métadonnées ont changé (empreinte du texte)."""
    provider = provider or embedding_provider()
    tracks = list(Track.objects.filter(status=TrackStatus.PRET).select_related("source", "album"))
    todo: list[tuple[Track, str, str]] = []
    for track in tracks:
        text = embedding_text(track)
        digest = hashlib.sha256(text.encode()).hexdigest()
        if digest != track.embedding_text_hash:
            todo.append((track, text, digest))
    for start in range(0, len(todo), EMBED_BATCH):
        batch = todo[start : start + EMBED_BATCH]
        vectors = provider.embed_texts([text for _, text, _ in batch])
        for (track, _, digest), vector in zip(batch, vectors, strict=True):
            array = np.asarray(vector, dtype=np.float32)
            # Vecteur nul (fournisseur « stub ») : inutilisable en cosinus, on n'enregistre rien.
            track.embedding = array.tolist() if array.size and float(np.linalg.norm(array)) > 0 else None
            track.embedding_text_hash = digest
        Track.objects.bulk_update([t for t, _, _ in batch], ["embedding", "embedding_text_hash"], batch_size=200)
    return len(todo)


@transaction.atomic
def content_neighbors_compute(*, now: datetime.datetime | None = None) -> int:
    now = now or timezone.now()
    TrackNeighbor.objects.filter(method=NeighborMethod.CONTENU).delete()
    candidates = Track.objects.filter(status=TrackStatus.PRET, hidden_at__isnull=True, embedding__isnull=False)
    rows: list[TrackNeighbor] = []
    for track in candidates.only("pk", "embedding"):
        nearest = (
            candidates.exclude(pk=track.pk)
            .annotate(distance=CosineDistance("embedding", track.embedding))
            .order_by("distance")
            .values_list("pk", "distance")[: settings.AUDIO_RECO_NEIGHBORS]
        )
        rows += [
            TrackNeighbor(track=track, neighbor_id=pk, score=1.0 - d, method=NeighborMethod.CONTENU, computed_at=now)
            for pk, d in nearest
            if d is not None and 1.0 - d > 0
        ]
    TrackNeighbor.objects.bulk_create(rows, batch_size=1000)
    return len(rows)


# --- 3. Utilisateur → pistes -----------------------------------------------------------------

_SIGNALS_SQL = """
    SELECT e.user_id, e.track_id, 'ecoute' AS signal, max(e.occurred_at) AS at
    FROM audio_play_event e JOIN audio_track t ON t.id = e.track_id
    WHERE e.occurred_at >= %(since)s AND e.user_id IS NOT NULL
      AND (e.kind = 'complete'
           OR (e.kind = 'progress' AND t.duration_seconds > 0
               AND e.position_seconds >= %(ratio)s * t.duration_seconds))
    GROUP BY e.user_id, e.track_id
    UNION ALL
    SELECT l.user_id, l.track_id, 'like', l.created_at FROM audio_like l WHERE l.created_at >= %(since)s
    UNION ALL
    SELECT p.owner_id, i.track_id, 'playlist', i.added_at
    FROM audio_playlistitem i JOIN audio_playlist p ON p.id = i.playlist_id
    WHERE p.owner_id IS NOT NULL AND i.added_at >= %(since)s
"""
_SEEN_SQL = """
    SELECT DISTINCT user_id, track_id FROM audio_play_event
    WHERE occurred_at >= %(since)s AND user_id IS NOT NULL AND kind IN ('start', 'skip', 'complete', 'progress')
"""
SIGNAL_WEIGHT = {"ecoute": 1.0, "like": 1.5, "playlist": 1.0}
SIGNAL_VERB = {"ecoute": "écouté", "like": "aimé", "playlist": "ajouté à une playlist"}


def _neighbors_index() -> dict[str, list[tuple[str, float]]]:
    index: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for track_id, neighbor_id, score, method in TrackNeighbor.objects.values_list(
        "track_id", "neighbor_id", "score", "method"
    ):
        weight = 1.0 if method == NeighborMethod.COECOUTE else CONTENT_WEIGHT
        index[str(track_id)].append((str(neighbor_id), score * weight))
    return index


def _parish_sources(user: Any) -> list[AudioSource]:
    parish = getattr(user, "paroisse_suivie", None)
    if parish is None:
        return []
    prefixes = [parish.path[:i] for i in range(access.STEPLEN, len(parish.path) + 1, access.STEPLEN)]
    return list(AudioSource.objects.filter(is_active=True, node__path__in=prefixes))


def _user_recommendations(
    *,
    user: Any,
    seeds: list[tuple[str, str, datetime.datetime]],
    seen: set[str],
    neighbors: dict[str, list[tuple[str, float]]],
    titles: dict[str, str],
    season: str,
    now: datetime.datetime,
) -> list[UserRecommendation]:
    scores: dict[str, float] = defaultdict(float)
    reasons: dict[str, tuple[float, str, str | None]] = {}

    def add(track_id: str, value: float, reason: str, reason_track: str | None) -> None:
        scores[track_id] += value
        if track_id not in reasons or value > reasons[track_id][0]:
            reasons[track_id] = (value, reason, reason_track)

    for seed_id, signal, at in seeds:
        age_days = max(0.0, (now - at).total_seconds() / 86400)
        weight = SIGNAL_WEIGHT[signal] * 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)
        reason = f"Parce que vous avez {SIGNAL_VERB[signal]} « {titles.get(seed_id, '')} »"
        for neighbor_id, score in neighbors.get(seed_id, []):
            add(neighbor_id, weight * score, reason, seed_id)

    m = access.membership(user)
    listenable = access.listenable_tracks(m)
    sources = _parish_sources(user)
    if sources:
        since = now - datetime.timedelta(days=NEW_DAYS)
        for track_id, source_name in listenable.filter(source__in=sources, published_at__gte=since).values_list(
            "pk", "source__name"
        )[:200]:
            add(str(track_id), PARISH_BONUS, f"Nouveauté de {source_name}", None)
    if season:
        for track_id in listenable.filter(Q(liturgical_season=season) | Q(album__liturgical_season=season)).order_by(
            "-published_at"
        ).values_list("pk", flat=True)[:200]:
            add(str(track_id), SEASON_BONUS, season_reason(season), None)

    excluded = seen | {s for s, _, _ in seeds}
    candidates = [t for t in scores if t not in excluded]
    allowed = {str(pk) for pk in listenable.filter(pk__in=candidates).values_list("pk", flat=True)}
    ranked = sorted((t for t in candidates if t in allowed), key=lambda t: (-scores[t], t))
    return [
        UserRecommendation(
            user=user,
            track_id=t,
            score=round(scores[t], 6),
            reason=reasons[t][1][:300],
            reason_track_id=reasons[t][2],
            computed_at=now,
        )
        for t in ranked[: settings.AUDIO_RECO_PER_USER]
    ]


def user_recommendations_compute(*, now: datetime.datetime | None = None) -> int:
    """Recalcule les recommandations de chaque utilisateur actif (signaux des 90 derniers jours)."""
    from apps.users.models import BaseUser

    now = now or timezone.now()
    params: dict[str, Any] = {
        "since": now - datetime.timedelta(days=settings.AUDIO_RECO_WINDOW_DAYS),
        "ratio": settings.AUDIO_RECO_COMPLETE_RATIO,
    }
    seeds: dict[Any, list[tuple[str, str, datetime.datetime]]] = defaultdict(list)
    seen: dict[Any, set[str]] = defaultdict(set)
    with connection.cursor() as cursor:
        cursor.execute(_SIGNALS_SQL, params)
        for user_id, track_id, signal, at in cursor.fetchall():
            seeds[user_id].append((str(track_id), signal, at))
        cursor.execute(_SEEN_SQL, params)
        for user_id, track_id in cursor.fetchall():
            seen[user_id].add(str(track_id))

    opted_out = set(ListenerSettings.objects.filter(recommendations_enabled=False).values_list("user_id", flat=True))
    user_ids = (set(seeds) | set(seen)) - opted_out
    neighbors = _neighbors_index()
    titles = {str(pk): title for pk, title in Track.objects.values_list("pk", "title")}
    season = current_season(timezone.localdate(now))
    total = 0
    for user in BaseUser.objects.filter(pk__in=user_ids, is_active=True).select_related("paroisse_suivie"):
        recos = _user_recommendations(
            user=user,
            seeds=seeds.get(user.pk, []),
            seen=seen.get(user.pk, set()),
            neighbors=neighbors,
            titles=titles,
            season=season,
            now=now,
        )
        with transaction.atomic():
            UserRecommendation.objects.filter(user=user).delete()
            UserRecommendation.objects.bulk_create(recos)
        cache.delete(user_reco_cache_key(user.pk))
        total += len(recos)
    # Recommandations des personnes devenues inactives ou qui ont désactivé le réglage.
    UserRecommendation.objects.filter(Q(computed_at__lt=now - datetime.timedelta(days=7)) | Q(user_id__in=opted_out)).delete()
    return total


def recompute_all(*, now: datetime.datetime | None = None, provider: Any = None) -> dict[str, Any]:
    """Tâche nocturne complète (``audio_reco_recompute_task``)."""
    if not settings.AUDIO_RECO_ENABLED:
        return {"desactive": True}
    now = now or timezone.now()
    embedded = track_embeddings_refresh(provider=provider)
    colisten = colisten_neighbors_compute(now=now)
    content = content_neighbors_compute(now=now)
    users = user_recommendations_compute(now=now)
    logger.info("audio.reco.recompute", extra={"coecoute": colisten, "contenu": content, "recommandations": users})
    return {"embeddings": embedded, "voisins_coecoute": colisten, "voisins_contenu": content, "recommandations": users}
