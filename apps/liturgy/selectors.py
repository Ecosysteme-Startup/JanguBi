"""Jour liturgique V1 (SRS EF-PAR-01, -02, -05 ; ADR-008).

Le calendrier (temps, couleur, célébration, cycles) est calculé localement. Les lectures
viennent de la source configurée :
- ``aelf`` (défaut) : la réponse de l'API AELF telle quelle — ``text`` = ``contenu`` et ``aelf`` = l'objet
  lecture AELF stocké sans transformation (titre, intro_lue, refrain_psalmique, verset_evangile…) ;
- ``crampon_refs`` : seules les références du jour sont reprises, le texte est celui de la Bible locale.
"""

import datetime
from typing import Any

from django.conf import settings
from django.db.models import Prefetch, Q

from apps.bible.editions import current_edition, edition_filter
from apps.bible.models import Verse
from apps.liturgy.calendar import liturgical_day
from apps.liturgy.models import LiturgicalDate, Reading

AELF_NOTICE = "Textes liturgiques © AELF, reproduits avec son autorisation."
CRAMPON_NOTICE = "Références du jour ; texte de la Bible Crampon (1923), domaine public."


def liturgical_date_get(*, day: datetime.date, zone: str | None = None) -> LiturgicalDate | None:
    verses = edition_filter(Verse.objects.select_related("chapter", "chapter__book")).order_by("number")
    return (
        LiturgicalDate.objects.filter(date=day, zone=zone or settings.LITURGY_ZONE)
        .prefetch_related(
            Prefetch(
                "readings",
                queryset=Reading.objects.order_by("id").prefetch_related(Prefetch("matched_verses", queryset=verses)),
            )
        )
        .select_related("resource")
        .first()
    )


def _reading_verses(reading: Reading) -> list[Verse]:
    """Versets de la lecture. Le rattachement est fait à l'import AELF ; s'il manque (Bible importée
    après les lectures, ou réimportée, ce qui vide le lien), on le recalcule à la volée depuis la
    référence plutôt que de servir une lecture sans texte. `liturgy_link_verses` le rend durable."""
    verses = list(reading.matched_verses.all())
    if verses or not reading.citation:
        return verses
    from apps.liturgy.matcher import CitationMatcher

    return CitationMatcher.match(reading.citation)


def _reading(reading: Reading, *, source: str) -> dict[str, Any]:
    verses = (
        [
            {"book": v.chapter.book.name, "chapter": v.chapter.number, "number": v.number, "text": v.text}
            for v in _reading_verses(reading)
        ]
        if source == "crampon_refs"
        else []
    )
    return {
        "type": reading.type,
        "citation": reading.citation,
        "text": reading.text if source == "aelf" else None,
        "verses": verses,
        # Objet lecture AELF tel que reçu (Reading.raw_metadata), sans renommage ni reconstruction.
        "aelf": (reading.raw_metadata or {}) if source == "aelf" else None,
    }


def meditation_for(*, day: datetime.date, user: Any = None) -> dict[str, Any] | None:
    """EF-PAR-05 : méditation du jour publiée pour la paroisse suivie (ou ses ancêtres), sinon globale."""
    from apps.hierarchy.selectors import node_ancestors
    from apps.news.models import Article

    scope = Q(scope_node__isnull=True)
    parish = getattr(user, "paroisse_suivie", None) if getattr(user, "is_authenticated", False) else None
    if parish is not None:
        scope |= Q(scope_node_id__in=[parish.pk, *node_ancestors(node=parish).values_list("pk", flat=True)])
    article = (
        Article.objects.filter(
            scope,
            content_type=Article.ContentType.MEDITATION,
            status=Article.Status.PUBLISHED,
            published_at__date=day,
        )
        .select_related("author__profile", "scope_node")
        .order_by("-scope_node__depth", "-published_at")
        .first()
    )
    if article is None:
        return None
    profile = getattr(article.author, "profile", None)
    author = f"{getattr(profile, 'first_name', '')} {getattr(profile, 'last_name', '')}".strip()
    return {
        "id": str(article.id),
        "title": article.title,
        "scope": article.scope_node.name if article.scope_node else None,
        # Plus besoin d'un second appel à /news/{id}/ pour la carte (écart F9).
        "excerpt": article.excerpt or None,
        "author_name": author or "Jàngu Bi",
        "published_at": article.published_at.isoformat() if article.published_at else None,
    }


def liturgy_day(*, day: datetime.date, user: Any = None) -> dict[str, Any]:
    source = settings.LITURGY_SOURCE
    date_obj = liturgical_date_get(day=day)
    readings = [_reading(r, source=source) for r in date_obj.readings.all()] if date_obj else []
    resource = getattr(date_obj, "resource", None) if date_obj else None
    return {
        "date": day.isoformat(),
        "calendar": liturgical_day(day).as_dict(),
        "source": source,
        "edition": current_edition() if source == "crampon_refs" else None,
        "notice": AELF_NOTICE if source == "aelf" else CRAMPON_NOTICE,
        "readings_available": date_obj is not None,
        "readings": readings,
        "audio_url": getattr(resource, "audio_url", None) if source == "aelf" else None,
        "meditation": meditation_for(day=day, user=user),
    }
