"""Signaux de lecture, signets et réglage de personnalisation (plan V2 §6).

Écritures seulement. Les signaux et les recommandations sont des données religieuses
sensibles (loi 2008-12) : rien de leur contenu n'est journalisé.
"""

import datetime
import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.bible.models import (
    Bookmark,
    Chapter,
    DailyRecommendation,
    ParolePreference,
    ReadingEvent,
    Verse,
)
from apps.core.exceptions import ApplicationError, NotFoundError

logger = logging.getLogger(__name__)

MAX_EVENTS_PER_BATCH = 200


def personnalisation_enabled(*, user: Any) -> bool:
    pref = ParolePreference.objects.filter(user=user).only("personnalisation_parole").first()
    return True if pref is None else pref.personnalisation_parole


@transaction.atomic
def parole_preference_update(*, user: Any, personnalisation_parole: bool) -> ParolePreference:
    """Désactiver la personnalisation arrête la collecte et retire les recommandations
    précalculées (l'historique existant s'efface avec ``reading_history_clear``)."""
    pref, _ = ParolePreference.objects.get_or_create(user=user)
    pref.personnalisation_parole = personnalisation_parole
    pref.save(update_fields=["personnalisation_parole", "updated_at"])
    if not personnalisation_parole:
        DailyRecommendation.objects.filter(user=user).delete()
    return pref


def _resolve_refs(events: list[dict[str, Any]]) -> tuple[dict[int, Verse], dict[tuple[int, int], Chapter]]:
    verse_ids = {e[k] for e in events for k in ("verset_debut_id", "verset_fin_id") if e.get(k)}
    verses = Verse.objects.select_related("chapter").in_bulk(verse_ids) if verse_ids else {}
    pairs = {(e["livre_id"], e["chapitre"]) for e in events if e.get("livre_id") and e.get("chapitre")}
    chapters: dict[tuple[int, int], Chapter] = {}
    if pairs:
        from django.db.models import Q

        cond = Q()
        for book_id, number in pairs:
            cond |= Q(book_id=book_id, number=number)
        chapters = {(c.book_id, c.number): c for c in Chapter.objects.filter(cond)}
    return verses, chapters


def _build_event(
    *, user: Any, raw: dict[str, Any], verses: dict[int, Verse], chapters: dict[tuple[int, int], Chapter], now: datetime.datetime
) -> ReadingEvent | None:
    start = verses.get(raw.get("verset_debut_id") or 0)
    end = verses.get(raw.get("verset_fin_id") or 0)
    if (raw.get("verset_debut_id") and start is None) or (raw.get("verset_fin_id") and end is None):
        return None
    if end is not None and start is None:
        start, end = end, None
    chapter = start.chapter if start is not None else chapters.get((raw.get("livre_id") or 0, raw.get("chapitre") or 0))
    if chapter is None:
        return None
    if end is not None:
        # Une plage reste dans un chapitre ; on la remet dans l'ordre si besoin.
        if end.chapter_id != start.chapter_id:  # type: ignore[union-attr]
            return None
        if end.number < start.number:  # type: ignore[union-attr]
            start, end = end, start
    return ReadingEvent(
        user=user,
        client_event_id=raw["client_event_id"],
        kind=raw["type"],
        chapter=chapter,
        verse_start=start,
        verse_end=end,
        finished=bool(raw.get("termine", False)),
        # Horloge du téléphone en avance : un événement « dans le futur » est ramené à maintenant.
        occurred_at=min(raw["occurred_at"], now),
    )


@transaction.atomic
def reading_events_record(*, user: Any, events: list[dict[str, Any]]) -> dict[str, Any]:
    """Enregistre un lot de signaux. Idempotent : un ``client_event_id`` déjà reçu est ignoré.

    Les événements dont la référence est inconnue (verset supprimé, chapitre inexistant) sont
    rejetés un par un, sans bloquer le lot : la file hors ligne du téléphone se vide quand même.
    """
    if len(events) > MAX_EVENTS_PER_BATCH:
        raise ApplicationError(
            f"Au plus {MAX_EVENTS_PER_BATCH} événements par envoi.", code="too_many_events"
        )
    received = len(events)
    if not personnalisation_enabled(user=user):
        return {"recus": received, "enregistres": 0, "rejetes": [], "personnalisation_parole": False}

    now = timezone.now()
    verses, chapters = _resolve_refs(events)
    rejected: list[str] = []
    to_create: dict[str, ReadingEvent] = {}
    for raw in events:
        event = _build_event(user=user, raw=raw, verses=verses, chapters=chapters, now=now)
        if event is None:
            rejected.append(raw["client_event_id"])
        else:
            to_create.setdefault(event.client_event_id, event)

    already = set(
        ReadingEvent.objects.filter(user=user, client_event_id__in=list(to_create)).values_list(
            "client_event_id", flat=True
        )
    )
    new = [e for cid, e in to_create.items() if cid not in already]
    ReadingEvent.objects.bulk_create(new, ignore_conflicts=True)
    return {"recus": received, "enregistres": len(new), "rejetes": rejected, "personnalisation_parole": True}


@transaction.atomic
def reading_history_clear(*, user: Any) -> int:
    """Efface l'historique de lecture et ce qui en a été déduit. Les signets restent : ce sont
    des contenus du fidèle, qu'il gère lui-même."""
    deleted, _ = ReadingEvent.objects.filter(user=user).delete()
    DailyRecommendation.objects.filter(user=user).delete()
    return deleted


@transaction.atomic
def parole_data_forget(*, user: Any) -> None:
    """Suppression du compte : tout ce que la Parole garde sur la personne."""
    ReadingEvent.objects.filter(user=user).delete()
    DailyRecommendation.objects.filter(user=user).delete()
    Bookmark.objects.filter(user=user).delete()
    ParolePreference.objects.filter(user=user).delete()


# ─── Signets et surlignages ───────────────────────────────────────────────────


@transaction.atomic
def bookmark_upsert(*, user: Any, verse_id: int, color: str = "", note: str = "") -> Bookmark:
    """Un seul signet par verset : reposer un signet met à jour couleur et note."""
    if not Verse.objects.filter(pk=verse_id).exists():
        raise NotFoundError("Verset introuvable.")
    bookmark, _ = Bookmark.objects.update_or_create(
        user=user, verse_id=verse_id, defaults={"color": color, "note": note}
    )
    return bookmark


@transaction.atomic
def bookmark_update(*, bookmark: Bookmark, data: dict[str, Any]) -> Bookmark:
    fields = [f for f in ("color", "note") if f in data]
    for field in fields:
        setattr(bookmark, field, data[field])
    if fields:
        bookmark.save(update_fields=[*fields, "updated_at"])
    return bookmark


@transaction.atomic
def bookmark_delete(*, bookmark: Bookmark) -> None:
    bookmark.delete()
