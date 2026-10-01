"""Recommandations de la sonothèque, précalculées chaque nuit (plan suite V2, §5.5).

1. **Item → item par co-écoute** : cosinus sur la matrice binaire utilisateur × piste des
   90 derniers jours (écoutes complètes, likes, ajouts en playlist), calculé en SQL ; 50 voisins
   par piste au plus, avec au moins ``AUDIO_RECO_MIN_CO_LISTENERS`` auditeurs communs.
2. **Contenu** : proximité des métadonnées structurées, en SQL (même album, temps liturgique,
   mots-clés et interprètes communs, source, compositeur, titres proches par trigrammes) ; sert
   aux pistes neuves sans historique. Sans IA ni modèle (ADR-018).
3. **Utilisateur → pistes** : voisins de ses écoutes et likes récents (pondérés par la récence),
   nouveautés de sa paroisse, temps liturgique ; on retire ce qu'il a déjà écouté ou passé ; 100
   au plus, en table et en cache Redis, chacune avec une explication lisible.

Garde-fous : aucune donnée sensible (dons, confessions, messagerie) ; interrupteur global
``AUDIO_RECO_ENABLED`` ; réglage par personne (``ListenerSettings.recommendations_enabled``).
"""

import datetime
import logging
from collections import defaultdict
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from apps.audio import access
from apps.audio.enums import LiturgicalSeason, NeighborMethod
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
# Seuil de voisinage « contenu » : la même source seule (0,10) suffit, pour qu'une piste neuve sans album
# se rattache au moins aux autres chants de sa chorale ; un simple titre proche ne suffit pas.
CONTENT_MIN_SCORE = 0.1
# Pistes comparées par critère partagé (les plus récentes) : borne le coût du calcul (voir _CONTENT_SQL).
CONTENT_POOL = 100
USER_RECO_CACHE_SECONDS = 26 * 3600


def user_reco_cache_key(user_id: Any) -> str:
    return f"audio:reco:v1:{user_id}"


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

# Proximité de deux pistes prêtes, visibles, entre 0 et 1 (somme des poids) : même album 0,30 ;
# même temps liturgique (le sien, sinon celui de l'album) 0,15 ; mots-clés communs 0,25 × Jaccard ;
# même source 0,10 ; même compositeur 0,05 ; interprètes communs 0,05 × Jaccard ; titres proches
# 0,10 × similarité trigramme. Chaque égalité passe par coalesce : un album ou un temps absent d'un
# seul côté donnerait NULL, et NULL annulerait toute la somme.
#
# Coût borné : comparer toutes les pistes d'un même temps liturgique (5 valeurs) ou d'une même source
# serait quadratique (8,6 M paires pour 5 000 pistes). Chaque piste porte des « clés » (sa source, son
# temps, son compositeur, chacun de ses mots-clés et interprètes) ; elle n'est comparée qu'aux
# CONTENT_POOL pistes les plus récentes de chacune de ses clés, plus à celles de son album. Les
# intersections de mots-clés et d'interprètes se comptent sur les clés partagées : aucune
# sous-requête par paire.
_CONTENT_SQL = """
WITH t AS MATERIALIZED (
    SELECT tr.id, tr.album_id, tr.source_id, tr.title, lower(tr.composer) AS composer, tr.published_at,
           coalesce(nullif(tr.liturgical_season, ''), nullif(al.liturgical_season, '')) AS season,
           (SELECT count(DISTINCT lower(x)) FROM unnest(tr.tags) AS x) AS n_tags,
           (SELECT count(DISTINCT lower(x)) FROM unnest(tr.performers) AS x) AS n_perf,
           tr.tags, tr.performers
    FROM audio_track tr LEFT JOIN audio_album al ON al.id = tr.album_id
    WHERE tr.status = 'pret' AND tr.hidden_at IS NULL
),
keys AS MATERIALIZED (
    SELECT DISTINCT id, published_at, kind, v FROM (
        SELECT id, published_at, 'source' AS kind, source_id::text AS v FROM t
        UNION ALL SELECT id, published_at, 'saison', season FROM t WHERE season IS NOT NULL
        UNION ALL SELECT id, published_at, 'compositeur', composer FROM t WHERE composer <> ''
        UNION ALL SELECT t.id, t.published_at, 'mot', lower(x) FROM t, unnest(t.tags) AS x
        UNION ALL SELECT t.id, t.published_at, 'interprete', lower(x) FROM t, unnest(t.performers) AS x
    ) k
),
pool AS MATERIALIZED (
    SELECT * FROM (
        SELECT id, kind, v, row_number() OVER (PARTITION BY kind, v ORDER BY published_at DESC NULLS LAST, id) AS rk
        FROM keys
    ) r WHERE rk <= %(pool)s
),
shared AS (
    SELECT ka.id AS t1, p.id AS t2,
           count(*) FILTER (WHERE ka.kind = 'mot') AS mots,
           count(*) FILTER (WHERE ka.kind = 'interprete') AS interpretes
    FROM keys ka JOIN pool p ON p.kind = ka.kind AND p.v = ka.v AND p.id <> ka.id
    GROUP BY ka.id, p.id
),
paires AS (
    SELECT t1, t2, mots, interpretes FROM shared
    UNION ALL
    SELECT a.id, b.id, 0, 0 FROM t a JOIN t b ON a.album_id = b.album_id AND a.id <> b.id
),
candidates AS (
    SELECT t1, t2, max(mots) AS mots, max(interpretes) AS interpretes FROM paires GROUP BY t1, t2
),
scored AS (
    SELECT c.t1, c.t2,
        0.30 * coalesce(a.album_id = b.album_id, false)::int
      + 0.15 * coalesce(a.season = b.season, false)::int
      + 0.25 * coalesce(c.mots::float / nullif(a.n_tags + b.n_tags - c.mots, 0), 0)
      + 0.10 * (a.source_id = b.source_id)::int
      + 0.05 * (a.composer <> '' AND a.composer = b.composer)::int
      + 0.05 * coalesce(c.interpretes::float / nullif(a.n_perf + b.n_perf - c.interpretes, 0), 0)
      + 0.10 * similarity(a.title, b.title) AS score
    FROM candidates c JOIN t a ON a.id = c.t1 JOIN t b ON b.id = c.t2
),
ranked AS (
    SELECT t1, t2, score, row_number() OVER (PARTITION BY t1 ORDER BY score DESC, t2) AS rk
    FROM scored WHERE score >= %(min_score)s
)
INSERT INTO audio_trackneighbor (track_id, neighbor_id, score, method, computed_at)
SELECT t1, t2, score, 'contenu', %(now)s FROM ranked WHERE rk <= %(top)s
"""


@transaction.atomic
def content_neighbors_compute(*, now: datetime.datetime | None = None) -> int:
    now = now or timezone.now()
    TrackNeighbor.objects.filter(method=NeighborMethod.CONTENU).delete()
    params: dict[str, Any] = {
        "min_score": CONTENT_MIN_SCORE,
        "now": now,
        "top": settings.AUDIO_RECO_NEIGHBORS,
        "pool": CONTENT_POOL,
    }
    with connection.cursor() as cursor:
        cursor.execute(_CONTENT_SQL, params)
        return cursor.rowcount


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
        for track_id in (
            listenable.filter(Q(liturgical_season=season) | Q(album__liturgical_season=season))
            .order_by("-published_at")
            .values_list("pk", flat=True)[:200]
        ):
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
    UserRecommendation.objects.filter(
        Q(computed_at__lt=now - datetime.timedelta(days=7)) | Q(user_id__in=opted_out)
    ).delete()
    return total


def recompute_all(*, now: datetime.datetime | None = None) -> dict[str, Any]:
    """Tâche nocturne complète (``audio_reco_recompute_task``)."""
    if not settings.AUDIO_RECO_ENABLED:
        return {"desactive": True}
    now = now or timezone.now()
    colisten = colisten_neighbors_compute(now=now)
    content = content_neighbors_compute(now=now)
    users = user_recommendations_compute(now=now)
    logger.info("audio.reco.recompute", extra={"coecoute": colisten, "contenu": content, "recommandations": users})
    return {"voisins_coecoute": colisten, "voisins_contenu": content, "recommandations": users}
