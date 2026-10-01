from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import QuerySet

if TYPE_CHECKING:  # seulement pour l'IDE/mypy
    from apps.bible.models import HomilieNote, ReadingPlan


def homilenote_list(*, author) -> QuerySet:
    from apps.bible.models import HomilieNote

    return (
        HomilieNote.objects.filter(author=author).select_related("passage_start", "passage_end").order_by("-created_at")
    )


def homilenote_get(*, note_id: int, user) -> "HomilieNote":
    from apps.bible.models import HomilieNote
    from apps.core.exceptions import ApplicationError

    try:
        return HomilieNote.objects.select_related("passage_start", "passage_end").get(pk=note_id, author=user)
    except HomilieNote.DoesNotExist:
        raise ApplicationError("Note introuvable.")


def lectio_divina_get_for_verse(*, user, passage_id: int):
    from apps.bible.models import LectioDivinaSession

    return LectioDivinaSession.objects.filter(user=user, passage_id=passage_id).first()


def lectio_divina_list(*, user) -> QuerySet:
    from apps.bible.models import LectioDivinaSession

    return LectioDivinaSession.objects.filter(user=user).select_related("passage").order_by("-updated_at")


def _annotate_is_subscribed(qs: QuerySet, user) -> QuerySet:
    """Ajoute `is_subscribed` en une sous-requête EXISTS (pas de N+1 en liste)."""
    from django.db.models import Exists, OuterRef, Value

    from apps.bible.models import ReadingPlanSubscription

    if user is None or not getattr(user, "is_authenticated", False):
        return qs.annotate(is_subscribed=Value(False))

    return qs.annotate(is_subscribed=Exists(ReadingPlanSubscription.objects.filter(plan=OuterRef("pk"), user=user)))


def reading_plan_list(*, published_only: bool = True, user=None) -> QuerySet:
    from apps.bible.models import ReadingPlan

    qs = ReadingPlan.objects.select_related("author")
    if published_only:
        qs = qs.filter(is_published=True)
    return _annotate_is_subscribed(qs, user).order_by("-created_at")


def reading_plan_get(*, plan_id: int, user=None) -> "ReadingPlan":
    from apps.bible.models import ReadingPlan
    from apps.core.exceptions import ApplicationError

    qs = _annotate_is_subscribed(ReadingPlan.objects.prefetch_related("plan_passages__verse"), user)
    try:
        return qs.get(pk=plan_id)
    except ReadingPlan.DoesNotExist:
        raise ApplicationError("Plan de lecture introuvable.")


# ─── « Pour vous aujourd'hui », signets, réglages (plan V2 §6) ────────────────


def bookmark_list(*, user) -> QuerySet:
    from apps.bible.models import Bookmark

    return Bookmark.objects.filter(user=user).select_related("verse__chapter__book").order_by("-updated_at")


def bookmark_get(*, user, bookmark_id: int):
    from apps.core.exceptions import NotFoundError

    bookmark = bookmark_list(user=user).filter(pk=bookmark_id).first()
    if bookmark is None:
        raise NotFoundError("Signet introuvable.")
    return bookmark


def parole_preference_get(*, user) -> dict:
    from apps.bible.services.reading_signals import personnalisation_enabled

    return {"personnalisation_parole": personnalisation_enabled(user=user)}


def daily_verse_get(*, day) -> dict | None:
    """Verset des lectures du jour (repli) : premier verset de l'évangile, sinon de la première lecture."""
    from django.conf import settings

    from apps.bible.editions import edition_filter
    from apps.bible.models import Verse
    from apps.bible.services.recommendation_service import reading_kind, verse_payload
    from apps.liturgy.models import Reading

    readings = list(
        Reading.objects.filter(liturgical_date__date=day, liturgical_date__zone=settings.LITURGY_ZONE).order_by("id")
    )
    readings.sort(key=lambda r: 0 if reading_kind(r.type) == "evangile" else 1)
    for reading in readings:
        verse = (
            edition_filter(Verse.objects.filter(liturgy_readings=reading))
            .select_related("chapter__book")
            .order_by("chapter__number", "number")
            .first()
        )
        if verse is not None:
            label = (
                "Tiré de l'évangile du jour"
                if reading_kind(reading.type) == "evangile"
                else "Tiré des lectures du jour"
            )
            return verse_payload(verse, raisons=[label])
    return None


def pour_vous_get(*, user, day) -> dict:
    """Lit le précalcul de la nuit ; sinon (démarrage à froid, fidèle inactif, personnalisation
    désactivée) sert le verset des lectures du jour."""
    from apps.bible.models import DailyRecommendation
    from apps.bible.services.reading_signals import personnalisation_enabled
    from apps.bible.services.recommendation_service import continue_reading_get

    enabled = personnalisation_enabled(user=user)
    if enabled:
        row = DailyRecommendation.objects.filter(user=user, date=day).only("payload").first()
        if row is not None:
            return {"date": day.isoformat(), "personnalise": True, "personnalisation_parole": True, **row.payload}
    verse = daily_verse_get(day=day)
    return {
        "date": day.isoformat(),
        "personnalise": False,
        "personnalisation_parole": enabled,
        "verset": verse,
        "autres_versets": [],
        "lecture_a_continuer": continue_reading_get(user=user) if enabled else None,
        "livre_suggere": None,
        "plan_suggere": None,
        "raisons": verse["raisons"] if verse else [],
    }


def parole_personal_data(*, user) -> dict:
    """Export des données personnelles (EF-CONF-02) : ce que la Parole garde sur la personne."""
    from apps.bible.models import Bookmark, ReadingEvent

    def ref(verse):
        return f"{verse.chapter.book.name} {verse.chapter.number}, {verse.number}" if verse else None

    return {
        "reglages": parole_preference_get(user=user),
        "signets": [
            {"verset": ref(b.verse), "couleur": b.color, "note": b.note, "modifie_le": b.updated_at.isoformat()}
            for b in Bookmark.objects.filter(user=user).select_related("verse__chapter__book").order_by("created_at")
        ],
        "historique_de_lecture": [
            {
                "type": e.kind,
                "chapitre": f"{e.chapter.book.name} {e.chapter.number}",
                "verset_debut": e.verse_start.number if e.verse_start else None,
                "verset_fin": e.verse_end.number if e.verse_end else None,
                "termine": e.finished,
                "le": e.occurred_at.isoformat(),
            }
            for e in ReadingEvent.objects.filter(user=user)
            .select_related("chapter__book", "verse_start", "verse_end")
            .order_by("occurred_at")
        ],
    }
