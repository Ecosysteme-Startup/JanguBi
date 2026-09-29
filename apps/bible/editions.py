"""Édition biblique servie (ADR-008 : Crampon 1923 en V1)."""

from typing import Any

from django.conf import settings
from django.db.models import QuerySet


def current_edition() -> dict[str, str] | None:
    code = settings.BIBLE_EDITION
    if not code:
        return None
    return {"code": code, "label": settings.BIBLE_EDITIONS.get(code, code)}


def edition_filter(qs: QuerySet[Any], *, field: str = "source_file", requested: str | None = None) -> QuerySet[Any]:
    """Restreint aux versets de l'édition configurée ; une édition explicitement demandée
    n'est acceptée que si c'est elle (pas de contournement vers un texte non autorisé)."""
    code = settings.BIBLE_EDITION
    if code:
        return qs.filter(**{field: code})
    if requested:
        return qs.filter(**{field: requested})
    return qs
