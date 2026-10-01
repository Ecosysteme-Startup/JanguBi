"""« Pour vous aujourd'hui » : verset, lecture à continuer, livre et plan suggérés (plan V2 §6).

Sans IA ni modèle (ADR-018) : la proximité entre versets est **lexicale**, pondérée par la rareté
des mots dans toute la Bible (TF-IDF), et calculée dans PostgreSQL à partir de la colonne ``tsv``
(plein texte ``fr_unaccent``, index GIN existant).

Méthode :
- poids d'un mot = ``log((N + 1) / (df + 1))`` : un mot rare (« vigne », « talent ») compte
  beaucoup ; un mot présent dans plus de ``PAROLE_RECO_MAX_DF_RATIO`` des versets (« le », « dit »,
  « Dieu ») ne compte pas du tout — sinon un chapitre lu (trente versets) additionne trente fois
  ses mots courants, qui passent devant les mots rares et rendent la recherche lente ;
- profil du fidèle = mots des versets lus et marqués, chacun pondéré par le signal (lu, signet,
  surlignage…) et par la récence (moitié du poids tous les ``PAROLE_RECO_HALF_LIFE_DAYS`` jours) ;
  on garde les ``PROFILE_TERMS`` mots les plus lourds ;
- candidats = versets qui partagent ces mots (score = somme des poids des mots communs, rapportée
  à la longueur du verset), sans ce qui a été lu depuis ``PAROLE_RECO_EXCLUDE_READ_DAYS`` jours,
  avec un bonus pour la proximité avec l'évangile du jour, les lectures du jour et le temps
  liturgique ;
- diversité : au plus un verset par livre dans les trois premiers ;
- livre suggéré : livre non commencé qui rassemble le plus de candidats proches.

Garde-fous : aucun score n'est exposé ni stocké dans la charge utile, seulement des raisons
courtes (« En lien avec l'évangile du jour », « Parce que vous lisez Luc »).
"""

import datetime
import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

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
PROFILE_TERMS = 12  # mots retenus pour le profil d'un fidèle
LITURGY_TERMS = 12  # mots retenus pour l'évangile (ou les lectures) du jour

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


# ─── Outils lexicaux (SQL) ────────────────────────────────────────────────────


def _decay(age_days: float) -> float:
    return 0.5 ** (max(age_days, 0.0) / settings.PAROLE_RECO_HALF_LIFE_DAYS)


def _edition_sql(alias: str = "v") -> tuple[str, list[Any]]:
    """Filtre SQL de l'édition servie (même règle que ``editions.edition_filter``)."""
    if settings.BIBLE_EDITION:
        return f" AND {alias}.source_file = %s", [settings.BIBLE_EDITION]
    return "", []


def _document_frequencies() -> tuple[int, dict[str, int]]:
    """Nombre de versets indexés et, pour chaque mot (lexème), le nombre de versets qui le portent."""
    edition, params = _edition_sql()
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM bible_verse v WHERE v.tsv IS NOT NULL{edition}", params)
        total = int(cursor.fetchone()[0])
        cursor.execute(
            f"""
            SELECT t.term, count(*)
            FROM bible_verse v, unnest(tsvector_to_array(v.tsv)) AS t(term)
            WHERE v.tsv IS NOT NULL{edition}
            GROUP BY t.term
            """,
            params,
        )
        return total, {term: int(df) for term, df in cursor.fetchall()}


def _verse_terms(verse_ids: set[int]) -> dict[int, list[str]]:
    """verse_id -> mots (lexèmes) de son ``tsv``."""
    if not verse_ids:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, tsvector_to_array(tsv) FROM bible_verse WHERE id = ANY(%s) AND tsv IS NOT NULL",
            [list(verse_ids)],
        )
        return {vid: list(terms or []) for vid, terms in cursor.fetchall()}


def _top_terms(weights: dict[str, float], k: int) -> dict[str, float]:
    kept = sorted(((t, w) for t, w in weights.items() if w > 0), key=lambda tw: (-tw[1], tw[0]))[:k]
    return dict(kept)


def _tsquery(terms: dict[str, float]) -> str:
    """``'a' | 'b'`` : lexèmes déjà normalisés, donc cités tels quels (pas de retraitement)."""
    return " | ".join("'" + t.replace("'", "''") + "'" for t in terms)


def _lexical_scores(
    terms: dict[str, float], *, limit: int | None = None, verse_ids: list[int] | None = None
) -> dict[int, float]:
    """Score de proximité de chaque verset avec un ensemble de mots pondérés.

    Somme des poids des mots communs, rapportée à la racine du nombre de mots du verset (un long
    verset ne gagne pas du seul fait de sa longueur). L'index GIN sur ``tsv`` restreint d'abord aux
    versets qui portent au moins un des mots.
    """
    if not terms:
        return {}
    edition, edition_params = _edition_sql()
    where_ids, id_params = "", []
    if verse_ids is not None:
        if not verse_ids:
            return {}
        where_ids, id_params = " AND v.id = ANY(%s)", [verse_ids]
    sql = f"""
        WITH q(term, w) AS (SELECT * FROM unnest(%s::text[], %s::float8[]))
        SELECT v.id, sum(q.w) / sqrt(greatest(max(length(v.tsv)), 1)) AS score
        FROM bible_verse v
        CROSS JOIN LATERAL unnest(tsvector_to_array(v.tsv)) AS t(term)
        JOIN q ON q.term = t.term
        WHERE v.tsv @@ %s::tsquery{edition}{where_ids}
        GROUP BY v.id
        ORDER BY score DESC, v.id
    """
    params: list[Any] = [list(terms), list(terms.values()), _tsquery(terms), *edition_params, *id_params]
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return {vid: float(score) for vid, score in cursor.fetchall()}


# ─── Contexte partagé (calculé une fois par nuit) ─────────────────────────────


@dataclass
class LiturgyContext:
    """Lectures du jour : mots marquants, versets par type de lecture, temps liturgique."""

    season: str = ""
    terms: dict[str, float] = field(default_factory=dict)
    verse_types: dict[int, str] = field(default_factory=dict)  # verse_id -> type de lecture
    main_label: str = DEFAULT_READING_LABEL
    gospel_verse_ids: list[int] = field(default_factory=list)


@dataclass
class RecoContext:
    today: datetime.date
    liturgy: LiturgyContext
    total_verses: int
    document_frequencies: dict[str, int]

    def idf(self, term: str) -> float:
        """Rareté d'un mot : élevée s'il est rare, 0 s'il est trop courant pour départager des versets."""
        df = self.document_frequencies.get(term, 0)
        if df > settings.PAROLE_RECO_MAX_DF_RATIO * self.total_verses:
            return 0.0
        return math.log((self.total_verses + 1) / (df + 1))


def reading_kind(reading_type: str) -> str:
    t = (reading_type or "").lower()
    if "evangile" in t or "gospel" in t:
        return "evangile"
    if "psaume" in t or "psalm" in t:
        return "psaume"
    return "lecture"


def liturgy_context_build(*, day: datetime.date, idf: Any = None) -> LiturgyContext:
    from apps.bible.editions import edition_filter
    from apps.liturgy.calendar import liturgical_day
    from apps.liturgy.models import LiturgicalDate, Reading

    ctx = LiturgyContext(season=liturgical_day(day).season)
    date_obj = LiturgicalDate.objects.filter(date=day, zone=settings.LITURGY_ZONE).first()
    if date_obj is None:
        return ctx
    verse_kind: dict[int, str] = {}
    for reading in Reading.objects.filter(liturgical_date=date_obj).order_by("id"):
        kind = reading_kind(reading.type)
        for verse_id in reading.matched_verses.values_list("id", flat=True):
            # L'évangile l'emporte si un verset appartient à plusieurs lectures.
            if verse_kind.get(verse_id) != "evangile":
                verse_kind[verse_id] = kind
    if not verse_kind:
        return ctx
    verse_ids = list(
        edition_filter(Verse.objects.filter(pk__in=verse_kind, tsv__isnull=False))
        .order_by("chapter__book__order", "chapter__number", "number")
        .values_list("id", flat=True)
    )
    ctx.verse_types = {vid: verse_kind[vid] for vid in verse_ids}
    ctx.gospel_verse_ids = [vid for vid in verse_ids if verse_kind[vid] == "evangile"]
    # Les mots du jour suivent l'évangile quand il est là (c'est lui qu'on cite dans la raison).
    basis = ctx.gospel_verse_ids or verse_ids
    if idf is not None:
        weights: dict[str, float] = defaultdict(float)
        for terms in _verse_terms(set(basis)).values():
            for term in terms:
                weights[term] += idf(term)
        ctx.terms = _top_terms(weights, LITURGY_TERMS)
    ctx.main_label = READING_LABELS["evangile"] if ctx.gospel_verse_ids else DEFAULT_READING_LABEL
    return ctx


def reco_context_build(*, today: datetime.date) -> RecoContext:
    total, frequencies = _document_frequencies()
    ctx = RecoContext(today=today, liturgy=LiturgyContext(), total_verses=total, document_frequencies=frequencies)
    ctx.liturgy = liturgy_context_build(day=today, idf=ctx.idf)
    return ctx


# ─── Profil de lecture d'un fidèle ────────────────────────────────────────────


@dataclass
class ReadingProfile:
    terms: dict[str, float]
    excluded_verse_ids: set[int]
    started_book_ids: set[int]
    top_book: Book | None
    book_weights: dict[int, float] = field(default_factory=dict)


def _verses_of(chapter_ids: set[int]) -> dict[int, list[tuple[int, int]]]:
    """chapter_id -> [(verse_id, numéro)]."""
    from apps.bible.editions import edition_filter

    out: dict[int, list[tuple[int, int]]] = {}
    for vid, chapter_id, number in edition_filter(Verse.objects.filter(chapter_id__in=chapter_ids)).values_list(
        "id", "chapter_id", "number"
    ):
        out.setdefault(chapter_id, []).append((vid, number))
    return out


def reading_profile_build(*, user: Any, now: datetime.datetime, ctx: RecoContext | None = None) -> ReadingProfile:
    history_since = now - datetime.timedelta(days=settings.PAROLE_RECO_HISTORY_DAYS)
    exclude_since = now - datetime.timedelta(days=settings.PAROLE_RECO_EXCLUDE_READ_DAYS)

    events = list(
        ReadingEvent.objects.filter(user=user, occurred_at__gte=history_since).values(
            "kind", "chapter_id", "chapter__book_id", "verse_start__number", "verse_end__number", "occurred_at"
        )
    )
    bookmarks = list(
        Bookmark.objects.filter(user=user).values(
            "verse_id", "verse__chapter_id", "verse__chapter__book_id", "color", "updated_at"
        )
    )
    started_book_ids = set(
        ReadingEvent.objects.filter(user=user).order_by().values_list("chapter__book_id", flat=True).distinct()
    ) | {b["verse__chapter__book_id"] for b in bookmarks}

    verses_by_chapter = _verses_of({e["chapter_id"] for e in events})
    verse_weights: dict[int, float] = defaultdict(float)
    excluded: set[int] = set()
    book_weight: dict[int, float] = defaultdict(float)

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
        book_weight[event["chapter__book_id"]] += weight
        share = weight / len(verses)  # un chapitre lu compte comme un signal, pas trente
        for vid, _number in verses:
            verse_weights[vid] += share
            if event["occurred_at"] >= exclude_since:
                excluded.add(vid)

    for bm in bookmarks:
        excluded.add(bm["verse_id"])
        age = (now - bm["updated_at"]).total_seconds() / 86400
        weight = (HIGHLIGHT_WEIGHT if bm["color"] else BOOKMARK_WEIGHT) * _decay(age)
        verse_weights[bm["verse_id"]] += weight
        book_weight[bm["verse__chapter__book_id"]] += weight

    terms: dict[str, float] = {}
    if ctx is not None and verse_weights:
        term_weights: dict[str, float] = defaultdict(float)
        for vid, terms_of_verse in _verse_terms(set(verse_weights)).items():
            for term in terms_of_verse:
                term_weights[term] += verse_weights[vid] * ctx.idf(term)
        terms = _top_terms(term_weights, PROFILE_TERMS)

    top_book = None
    if book_weight:
        top_book = Book.objects.filter(pk=max(book_weight, key=lambda k: book_weight[k])).first()
    return ReadingProfile(
        terms=terms,
        excluded_verse_ids=excluded,
        started_book_ids=started_book_ids,
        top_book=top_book,
        book_weights=dict(book_weight),
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
    interest: float  # proximité avec le profil, normalisée (1 = le plus proche)
    liturgy_sim: float  # proximité avec l'évangile du jour, normalisée
    reading_kind: str | None


def _normalized(scores: dict[int, float]) -> dict[int, float]:
    top = max(scores.values(), default=0.0)
    return {vid: s / top for vid, s in scores.items()} if top > 0 else {}


def _candidates(*, profile: ReadingProfile, ctx: RecoContext) -> list[_Candidate]:
    interest = _normalized(_lexical_scores(profile.terms, limit=settings.PAROLE_RECO_CANDIDATES))
    # Les versets des lectures du jour sont toujours candidats, même hors des plus proches.
    ids = list(dict.fromkeys([*interest, *ctx.liturgy.verse_types]))
    ids = [vid for vid in ids if vid not in profile.excluded_verse_ids]
    if not ids:
        return []
    liturgy = _normalized(_lexical_scores(ctx.liturgy.terms, verse_ids=ids))
    books = {
        vid: (book_id, slug)
        for vid, book_id, slug in Verse.objects.filter(pk__in=ids).values_list(
            "id", "chapter__book_id", "chapter__book__slug"
        )
    }
    season_books = SEASON_BOOKS.get(ctx.liturgy.season, ())
    out = []
    for vid in ids:
        kind = ctx.liturgy.verse_types.get(vid)
        score = interest.get(vid, 0.0)
        if score <= 0 and not kind:
            continue  # ni proche du profil, ni lecture du jour
        book_id, slug = books[vid]
        liturgy_sim = liturgy.get(vid, 0.0)
        rank = score + settings.PAROLE_RECO_LITURGY_BONUS * liturgy_sim
        if kind:
            rank += settings.PAROLE_RECO_READING_BONUS
        if slug in season_books:
            rank += settings.PAROLE_RECO_SEASON_BONUS
        out.append(_Candidate(vid, book_id, slug, rank, score, liturgy_sim, kind))
    out.sort(key=lambda c: (-c.rank, c.verse_id))
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
    elif ctx.liturgy.terms and cand.liturgy_sim >= settings.PAROLE_RECO_LITURGY_REASON_MIN:
        reasons.append(ctx.liturgy.main_label)
    elif cand.book_slug in SEASON_BOOKS.get(ctx.liturgy.season, ()):
        reasons.append(SEASON_REASONS[ctx.liturgy.season])
    if profile.top_book is not None:
        reasons.append(f"Parce que vous lisez {profile.top_book.name}")
    return reasons[:2]


def _suggest_book(*, profile: ReadingProfile, candidates: list[_Candidate]) -> dict[str, Any] | None:
    """Livre non commencé qui rassemble le plus de proximité (trois meilleurs versets par livre)."""
    by_book: dict[int, list[float]] = defaultdict(list)
    for cand in candidates:
        if cand.book_id not in profile.started_book_ids and cand.interest > 0:
            by_book[cand.book_id].append(cand.interest)
    if not by_book:
        return None
    best = max(by_book, key=lambda b: (sum(sorted(by_book[b], reverse=True)[:3]), -b))
    book = Book.objects.get(pk=best)
    raison = f"Parce que vous lisez {profile.top_book.name}" if profile.top_book else "Proche de vos lectures"
    return {**book_payload(book), "raison": raison}


def _suggest_plan(*, user: Any, profile: ReadingProfile) -> dict[str, Any] | None:
    """Plan publié, non suivi, dont les passages couvrent le plus les livres lus par le fidèle."""
    from apps.core.modules import is_module_active

    # Les plans de lecture sont gelés en V1 (ADR-006, « bible.avance ») : pas de suggestion.
    if not is_module_active("bible.avance") or not profile.book_weights:
        return None
    from apps.bible.models import ReadingPlanSubscription

    subscribed = set(ReadingPlanSubscription.objects.filter(user=user).values_list("plan_id", flat=True))
    plans = {p.pk: p for p in ReadingPlan.objects.filter(is_published=True).exclude(pk__in=subscribed)}
    if not plans:
        return None
    affinity: dict[int, float] = defaultdict(float)
    for plan_id, book_id in ReadingPlanPassage.objects.filter(plan_id__in=plans).values_list(
        "plan_id", "verse__chapter__book_id"
    ):
        affinity[plan_id] += profile.book_weights.get(book_id, 0.0)
    if not affinity or max(affinity.values()) <= 0:
        return None
    plan = plans[max(affinity, key=lambda p: (affinity[p], -p))]
    return {"id": plan.pk, "titre": plan.title, "description": plan.description, "raison": "Proche de vos lectures"}


def recommendation_compute(
    *, user: Any, ctx: RecoContext, now: datetime.datetime | None = None
) -> dict[str, Any] | None:
    """Charge utile « Pour vous aujourd'hui » du fidèle, ou ``None`` s'il n'a aucun signal exploitable."""
    now = now or timezone.now()
    profile = reading_profile_build(user=user, now=now, ctx=ctx)
    if not profile.terms:
        return None
    candidates = _candidates(profile=profile, ctx=ctx)
    picked = _diversify(candidates)
    verses = Verse.objects.select_related("chapter__book").in_bulk([c.verse_id for c in picked])
    items = [verse_payload(verses[c.verse_id], raisons=_reasons(c, profile=profile, ctx=ctx)) for c in picked]
    main = items[0] if items else None
    return {
        "verset": main,
        "autres_versets": items[1:],
        "lecture_a_continuer": continue_reading_get(user=user),
        "livre_suggere": _suggest_book(profile=profile, candidates=candidates),
        "plan_suggere": _suggest_plan(user=user, profile=profile),
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
