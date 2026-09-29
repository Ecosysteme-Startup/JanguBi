"""« Pour vous aujourd'hui » : verset, lecture à continuer, livre et plan suggérés (plan V2 §6).

Méthode :
- vecteur d'intérêt = moyenne pondérée des embeddings (normalisés) des versets lus et marqués,
  chaque signal perdant la moitié de son poids tous les ``PAROLE_RECO_HALF_LIFE_DAYS`` jours ;
- voisins HNSW (cosinus) de ce vecteur, sans ce qui a été lu depuis
  ``PAROLE_RECO_EXCLUDE_READ_DAYS`` jours, avec un bonus pour la proximité avec les lectures
  du jour et le temps liturgique ;
- diversité : au plus un verset par livre dans les trois premiers ;
- livre suggéré : livre non commencé dont le centre (moyenne des versets) est le plus proche.

Garde-fous : aucun score n'est exposé ni stocké dans la charge utile, seulement des raisons
courtes (« En lien avec l'évangile du jour », « Parce que vous lisez Luc »).
"""

import datetime
import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from pgvector.django import CosineDistance

from apps.bible.editions import edition_filter
from apps.bible.models import (
    Book,
    Bookmark,
    Chapter,
    DailyRecommendation,
    ParolePreference,
    ReadingEvent,
    ReadingPlan,
    ReadingPlanPassage,
    Verse,
)

logger = logging.getLogger(__name__)

TOP_N = 3

KIND_WEIGHTS: dict[str, float] = {
    ReadingEvent.Kind.LU: 1.0,
    ReadingEvent.Kind.RECHERCHE: 1.0,
    ReadingEvent.Kind.SIGNET: 2.0,
    ReadingEvent.Kind.LECTIO: 2.0,
    ReadingEvent.Kind.SURLIGNE: 2.5,
}
BOOKMARK_WEIGHT = 2.0
HIGHLIGHT_WEIGHT = 2.5

# Livres « de saison » (bonus léger) et libellé de la raison affichée.
SEASON_BOOKS = {
    "avent": ("isaie", "luc", "matthieu"),
    "noel": ("luc", "jean", "matthieu"),
    "careme": ("psaumes", "exode", "matthieu", "marc"),
    "triduum": ("jean", "isaie", "psaumes"),
    "paques": ("actes", "jean", "1-pierre", "apocalypse"),
}
SEASON_REASONS = {
    "avent": "En ce temps de l'Avent",
    "noel": "En ce temps de Noël",
    "careme": "En ce temps du Carême",
    "triduum": "En ces jours saints",
    "paques": "En ce temps pascal",
}
READING_LABELS = {
    "evangile": "En lien avec l'évangile du jour",
    "psaume": "En lien avec le psaume du jour",
}
DEFAULT_READING_LABEL = "En lien avec les lectures du jour"


# ─── Outils vectoriels ────────────────────────────────────────────────────────


def _unit(vec: Any) -> np.ndarray | None:
    if vec is None:
        return None
    arr = np.asarray(vec, dtype=np.float64)
    norm = float(np.linalg.norm(arr))
    if norm == 0.0 or not math.isfinite(norm):
        return None  # vecteur nul (fournisseur « stub ») : aucun signal exploitable
    return arr / norm


def _cos(a: np.ndarray, b: np.ndarray | None) -> float:
    return float(np.dot(a, b)) if b is not None else 0.0


def _decay(age_days: float) -> float:
    return 0.5 ** (max(age_days, 0.0) / settings.PAROLE_RECO_HALF_LIFE_DAYS)


def _parse_vector(text: str) -> np.ndarray:
    return np.array([float(x) for x in text.strip("[]").split(",")], dtype=np.float64)


# ─── Contexte partagé (calculé une fois par nuit) ─────────────────────────────


@dataclass
class LiturgyContext:
    """Lectures du jour : vecteur moyen, versets par type de lecture, temps liturgique."""

    season: str = ""
    vector: np.ndarray | None = None
    verse_types: dict[int, str] = field(default_factory=dict)  # verse_id -> type de lecture
    main_label: str = DEFAULT_READING_LABEL
    gospel_verse_ids: list[int] = field(default_factory=list)


@dataclass
class RecoContext:
    today: datetime.date
    liturgy: LiturgyContext
    book_centroids: dict[int, np.ndarray]
    books: dict[int, Book]
    plans: list[tuple[ReadingPlan, np.ndarray]]


def reading_kind(reading_type: str) -> str:
    t = (reading_type or "").lower()
    if "evangile" in t or "gospel" in t:
        return "evangile"
    if "psaume" in t or "psalm" in t:
        return "psaume"
    return "lecture"


def liturgy_context_build(*, day: datetime.date) -> LiturgyContext:
    from apps.liturgy.calendar import liturgical_day
    from apps.liturgy.models import LiturgicalDate, Reading

    ctx = LiturgyContext(season=liturgical_day(day).season)
    date_obj = LiturgicalDate.objects.filter(date=day, zone=settings.LITURGY_ZONE).first()
    if date_obj is None:
        return ctx
    readings = list(Reading.objects.filter(liturgical_date=date_obj).order_by("id"))
    verse_kind: dict[int, str] = {}
    for reading in readings:
        kind = reading_kind(reading.type)
        for verse_id in reading.matched_verses.values_list("id", flat=True):
            # L'évangile l'emporte si un verset appartient à plusieurs lectures.
            if verse_kind.get(verse_id) != "evangile":
                verse_kind[verse_id] = kind
    if not verse_kind:
        return ctx
    verses = list(
        edition_filter(Verse.objects.filter(pk__in=verse_kind, embedding__isnull=False))
        .order_by("chapter__book__order", "chapter__number", "number")
        .values_list("id", "embedding")
    )
    ctx.verse_types = {vid: verse_kind[vid] for vid, _ in verses}
    ctx.gospel_verse_ids = [vid for vid, _ in verses if verse_kind[vid] == "evangile"]
    # Le vecteur du jour suit l'évangile quand il est là (c'est lui qu'on cite dans la raison).
    basis = [emb for vid, emb in verses if not ctx.gospel_verse_ids or verse_kind[vid] == "evangile"]
    units = [u for u in (_unit(e) for e in basis) if u is not None]
    if units:
        ctx.vector = _unit(np.sum(units, axis=0))
    ctx.main_label = READING_LABELS["evangile"] if ctx.gospel_verse_ids else DEFAULT_READING_LABEL
    return ctx


def _book_centroids() -> dict[int, np.ndarray]:
    sql = """
        SELECT c.book_id, AVG(v.embedding)::text
        FROM bible_verse v JOIN bible_chapter c ON c.id = v.chapter_id
        WHERE v.embedding IS NOT NULL {edition}
        GROUP BY c.book_id
    """
    params: list[Any] = []
    edition = ""
    if settings.BIBLE_EDITION:
        edition, params = "AND v.source_file = %s", [settings.BIBLE_EDITION]
    with connection.cursor() as cursor:
        cursor.execute(sql.format(edition=edition), params)
        rows = cursor.fetchall()
    out: dict[int, np.ndarray] = {}
    for book_id, text in rows:
        unit = _unit(_parse_vector(text))
        if unit is not None:
            out[book_id] = unit
    return out


def _plan_vectors() -> list[tuple[ReadingPlan, np.ndarray]]:
    from apps.core.modules import is_module_active

    # Les plans de lecture sont gelés en V1 (ADR-006, « bible.avance ») : pas de suggestion.
    if not is_module_active("bible.avance"):
        return []
    plans = {p.pk: p for p in ReadingPlan.objects.filter(is_published=True)}
    if not plans:
        return []
    grouped: dict[int, list[np.ndarray]] = {}
    for plan_id, emb in ReadingPlanPassage.objects.filter(
        plan_id__in=plans, verse__embedding__isnull=False
    ).values_list("plan_id", "verse__embedding"):
        unit = _unit(emb)
        if unit is not None:
            grouped.setdefault(plan_id, []).append(unit)
    out = []
    for plan_id, units in grouped.items():
        vec = _unit(np.sum(units, axis=0))
        if vec is not None:
            out.append((plans[plan_id], vec))
    return out


def reco_context_build(*, today: datetime.date) -> RecoContext:
    centroids = _book_centroids()
    return RecoContext(
        today=today,
        liturgy=liturgy_context_build(day=today),
        book_centroids=centroids,
        books=Book.objects.in_bulk(list(centroids)),
        plans=_plan_vectors(),
    )


# ─── Profil de lecture d'un fidèle ────────────────────────────────────────────


@dataclass
class ReadingProfile:
    interest: np.ndarray | None
    excluded_verse_ids: set[int]
    started_book_ids: set[int]
    top_book: Book | None


def _verses_of(chapter_ids: set[int]) -> dict[int, list[tuple[int, int, Any]]]:
    """chapter_id -> [(verse_id, numéro, embedding)]."""
    out: dict[int, list[tuple[int, int, Any]]] = {}
    rows = edition_filter(Verse.objects.filter(chapter_id__in=chapter_ids)).values_list(
        "id", "chapter_id", "number", "embedding"
    )
    for vid, chapter_id, number, emb in rows:
        out.setdefault(chapter_id, []).append((vid, number, emb))
    return out


def reading_profile_build(*, user: Any, now: datetime.datetime) -> ReadingProfile:
    history_since = now - datetime.timedelta(days=settings.PAROLE_RECO_HISTORY_DAYS)
    exclude_since = now - datetime.timedelta(days=settings.PAROLE_RECO_EXCLUDE_READ_DAYS)

    events = list(
        ReadingEvent.objects.filter(user=user, occurred_at__gte=history_since).values(
            "kind", "chapter_id", "chapter__book_id", "verse_start__number", "verse_end__number", "occurred_at"
        )
    )
    bookmarks = list(
        Bookmark.objects.filter(user=user).values("verse_id", "verse__chapter_id", "verse__chapter__book_id", "color", "updated_at")
    )
    started_book_ids = set(
        ReadingEvent.objects.filter(user=user).order_by().values_list("chapter__book_id", flat=True).distinct()
    ) | {b["verse__chapter__book_id"] for b in bookmarks}

    chapter_ids = {e["chapter_id"] for e in events} | {b["verse__chapter_id"] for b in bookmarks}
    verses_by_chapter = _verses_of(chapter_ids)

    weights: dict[int, float] = {}
    embeddings: dict[int, Any] = {}
    excluded: set[int] = set()
    book_weight: dict[int, float] = {}

    for event in events:
        verses = verses_by_chapter.get(event["chapter_id"], [])
        lo, hi = event["verse_start__number"], event["verse_end__number"]
        if lo is not None:
            hi = hi if hi is not None else lo
            verses = [v for v in verses if lo <= v[1] <= hi]
        if not verses:
            continue
        age = (now - event["occurred_at"]).total_seconds() / 86400
        weight = KIND_WEIGHTS.get(event["kind"], 1.0) * _decay(age)
        book_weight[event["chapter__book_id"]] = book_weight.get(event["chapter__book_id"], 0.0) + weight
        share = weight / len(verses)  # un chapitre lu compte comme un signal, pas trente
        for vid, _number, emb in verses:
            weights[vid] = weights.get(vid, 0.0) + share
            embeddings[vid] = emb
            if event["occurred_at"] >= exclude_since:
                excluded.add(vid)

    for bm in bookmarks:
        vid = bm["verse_id"]
        emb = next((v[2] for v in verses_by_chapter.get(bm["verse__chapter_id"], []) if v[0] == vid), None)
        excluded.add(vid)
        if emb is None:
            continue
        age = (now - bm["updated_at"]).total_seconds() / 86400
        weight = (HIGHLIGHT_WEIGHT if bm["color"] else BOOKMARK_WEIGHT) * _decay(age)
        weights[vid] = weights.get(vid, 0.0) + weight
        embeddings[vid] = emb
        book_id = bm["verse__chapter__book_id"]
        book_weight[book_id] = book_weight.get(book_id, 0.0) + weight

    acc = None
    for vid, weight in weights.items():
        unit = _unit(embeddings[vid])
        if unit is None:
            continue
        acc = unit * weight if acc is None else acc + unit * weight
    interest = _unit(acc) if acc is not None else None

    top_book = None
    if book_weight:
        top_book = Book.objects.filter(pk=max(book_weight, key=lambda k: book_weight[k])).first()
    return ReadingProfile(
        interest=interest, excluded_verse_ids=excluded, started_book_ids=started_book_ids, top_book=top_book
    )


# ─── Mise en forme ────────────────────────────────────────────────────────────


def book_payload(book: Book) -> dict[str, Any]:
    return {"id": book.pk, "nom": book.name, "slug": book.slug}


def verse_payload(verse: Verse, *, raisons: list[str]) -> dict[str, Any]:
    book = verse.chapter.book
    return {
        "id": verse.pk,
        "reference": f"{book.name} {verse.chapter.number}, {verse.number}",
        "livre": book_payload(book),
        "chapitre": verse.chapter.number,
        "numero": verse.number,
        "texte": verse.text,
        "raisons": raisons,
    }


def continue_reading_get(*, user: Any) -> dict[str, Any] | None:
    """Dernier chapitre ouvert et pas terminé ; s'il a été terminé, le chapitre suivant."""
    last = (
        ReadingEvent.objects.filter(user=user, kind=ReadingEvent.Kind.LU)
        .select_related("chapter__book", "verse_start", "verse_end")
        .order_by("-occurred_at", "-id")
        .first()
    )
    if last is None:
        return None
    chapter = last.chapter
    resume_at = None
    if last.finished:
        following = Chapter.objects.select_related("book").filter(book=chapter.book, number=chapter.number + 1).first()
        if following is None:
            return None
        chapter = following
    else:
        verse = last.verse_end or last.verse_start
        resume_at = verse.number if verse is not None else None
    return {
        "reference": f"{chapter.book.name} {chapter.number}",
        "livre": book_payload(chapter.book),
        "chapitre": chapter.number,
        "reprendre_au_verset": resume_at,
    }


# ─── Calcul ───────────────────────────────────────────────────────────────────


@dataclass
class _Candidate:
    verse_id: int
    book_id: int
    book_slug: str
    rank: float
    liturgy_sim: float
    reading_kind: str | None


def _candidates(*, profile: ReadingProfile, ctx: RecoContext) -> list[_Candidate]:
    assert profile.interest is not None
    interest = profile.interest.tolist()
    base = edition_filter(Verse.objects.filter(embedding__isnull=False))
    limit = settings.PAROLE_RECO_CANDIDATES
    with transaction.atomic():
        # L'index HNSW ne rend pas plus de `hnsw.ef_search` voisins (40 par défaut) : on
        # l'élargit le temps de la requête, sinon le filtre « déjà lu » viderait la liste.
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL hnsw.ef_search = %s", [max(40, min(limit, 1000))])
        nearest = list(
            base.annotate(distance=CosineDistance("embedding", interest))
            .order_by("distance")
            .values("id", "chapter__book_id", "chapter__book__slug", "distance", "embedding")[:limit]
        )
    # Les versets des lectures du jour sont toujours candidats, même hors des plus proches voisins.
    seen = {row["id"] for row in nearest}
    extra_ids = [vid for vid in ctx.liturgy.verse_types if vid not in seen]
    if extra_ids:
        nearest += list(
            base.filter(pk__in=extra_ids)
            .annotate(distance=CosineDistance("embedding", interest))
            .values("id", "chapter__book_id", "chapter__book__slug", "distance", "embedding")
        )

    season_books = SEASON_BOOKS.get(ctx.liturgy.season, ())
    out = []
    for row in nearest:
        distance = row["distance"]
        if row["id"] in profile.excluded_verse_ids or distance is None or not math.isfinite(distance):
            continue
        unit = _unit(row["embedding"])
        if unit is None:
            continue
        liturgy_sim = _cos(unit, ctx.liturgy.vector)
        kind = ctx.liturgy.verse_types.get(row["id"])
        rank = (1.0 - distance) + settings.PAROLE_RECO_LITURGY_BONUS * max(liturgy_sim, 0.0)
        if kind:
            rank += settings.PAROLE_RECO_READING_BONUS
        if row["chapter__book__slug"] in season_books:
            rank += settings.PAROLE_RECO_SEASON_BONUS
        out.append(
            _Candidate(row["id"], row["chapter__book_id"], row["chapter__book__slug"], rank, liturgy_sim, kind)
        )
    out.sort(key=lambda c: -c.rank)
    return out


def _diversify(candidates: list[_Candidate], n: int = TOP_N) -> list[_Candidate]:
    picked: list[_Candidate] = []
    books: set[int] = set()
    for cand in candidates:
        if cand.book_id in books:
            continue
        picked.append(cand)
        books.add(cand.book_id)
        if len(picked) == n:
            break
    return picked


def _reasons(cand: _Candidate, *, profile: ReadingProfile, ctx: RecoContext) -> list[str]:
    reasons = []
    if cand.reading_kind:
        reasons.append(READING_LABELS.get(cand.reading_kind, DEFAULT_READING_LABEL))
    elif ctx.liturgy.vector is not None and cand.liturgy_sim >= settings.PAROLE_RECO_LITURGY_REASON_MIN:
        reasons.append(ctx.liturgy.main_label)
    elif cand.book_slug in SEASON_BOOKS.get(ctx.liturgy.season, ()):
        reasons.append(SEASON_REASONS[ctx.liturgy.season])
    if profile.top_book is not None:
        reasons.append(f"Parce que vous lisez {profile.top_book.name}")
    return reasons[:2]


def _suggest_book(*, profile: ReadingProfile, ctx: RecoContext) -> dict[str, Any] | None:
    assert profile.interest is not None
    best = max(
        (
            (_cos(profile.interest, vec), book_id)
            for book_id, vec in ctx.book_centroids.items()
            if book_id not in profile.started_book_ids
        ),
        default=None,
    )
    if best is None:
        return None
    book = ctx.books[best[1]]
    raison = f"Parce que vous lisez {profile.top_book.name}" if profile.top_book else "Proche de vos lectures"
    return {**book_payload(book), "raison": raison}


def _suggest_plan(*, user: Any, profile: ReadingProfile, ctx: RecoContext) -> dict[str, Any] | None:
    if not ctx.plans:
        return None
    assert profile.interest is not None
    from apps.bible.models import ReadingPlanSubscription

    subscribed = set(ReadingPlanSubscription.objects.filter(user=user).values_list("plan_id", flat=True))
    options = [(_cos(profile.interest, vec), plan) for plan, vec in ctx.plans if plan.pk not in subscribed]
    if not options:
        return None
    plan = max(options, key=lambda o: o[0])[1]
    return {"id": plan.pk, "titre": plan.title, "description": plan.description, "raison": "Proche de vos lectures"}


def recommendation_compute(*, user: Any, ctx: RecoContext, now: datetime.datetime | None = None) -> dict[str, Any] | None:
    """Charge utile « Pour vous aujourd'hui » du fidèle, ou ``None`` s'il n'a aucun signal exploitable."""
    now = now or timezone.now()
    profile = reading_profile_build(user=user, now=now)
    if profile.interest is None:
        return None
    picked = _diversify(_candidates(profile=profile, ctx=ctx))
    verses = Verse.objects.select_related("chapter__book").in_bulk([c.verse_id for c in picked])
    items = [verse_payload(verses[c.verse_id], raisons=_reasons(c, profile=profile, ctx=ctx)) for c in picked]
    main = items[0] if items else None
    return {
        "verset": main,
        "autres_versets": items[1:],
        "lecture_a_continuer": continue_reading_get(user=user),
        "livre_suggere": _suggest_book(profile=profile, ctx=ctx),
        "plan_suggere": _suggest_plan(user=user, profile=profile, ctx=ctx),
        "raisons": main["raisons"] if main else [],
    }


# ─── Précalcul nocturne ───────────────────────────────────────────────────────


def active_users_for_reco(*, now: datetime.datetime):
    from apps.users.models import BaseUser

    since = now - datetime.timedelta(days=settings.PAROLE_RECO_ACTIVE_DAYS)
    disabled = ParolePreference.objects.filter(personnalisation_parole=False).values("user_id")
    return (
        BaseUser.objects.filter(is_active=True)
        .filter(Q(reading_events__occurred_at__gte=since) | Q(bible_bookmarks__updated_at__gte=since))
        .exclude(pk__in=disabled)
        .distinct()
    )


@transaction.atomic
def daily_recommendation_store(*, user: Any, day: datetime.date, payload: dict[str, Any]) -> DailyRecommendation:
    reco, _ = DailyRecommendation.objects.update_or_create(user=user, date=day, defaults={"payload": payload})
    return reco


def daily_recommendations_recompute(*, today: datetime.date | None = None) -> dict[str, int]:
    """Idempotent : relancer la tâche le même jour réécrit les mêmes lignes (une par fidèle et par jour)."""
    now = timezone.now()
    today = today or timezone.localdate()
    ctx = reco_context_build(today=today)
    stored = skipped = failed = 0
    for user in active_users_for_reco(now=now).iterator():
        try:
            payload = recommendation_compute(user=user, ctx=ctx, now=now)
        except Exception:  # un fidèle en erreur ne bloque pas les autres
            failed += 1
            logger.exception("reco.parole.echec", extra={"user_id": str(user.pk)})
            continue
        if payload is None or payload["verset"] is None:
            skipped += 1
            continue
        daily_recommendation_store(user=user, day=today, payload=payload)
        stored += 1
    purged, _ = DailyRecommendation.objects.filter(
        date__lt=today - datetime.timedelta(days=settings.PAROLE_RECO_RETENTION_DAYS)
    ).delete()
    logger.info("reco.parole.nuit", extra={"stored": stored, "skipped": skipped, "failed": failed, "purged": purged})
    return {"stored": stored, "skipped": skipped, "failed": failed, "purged": purged}
