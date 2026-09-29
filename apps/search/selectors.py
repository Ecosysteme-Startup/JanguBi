"""Recherche transverse (lot V1-routes, B03) : Bible, paroisses, lieux, annonces, prêtres,
sonothèque. Lecture seule, aucun modèle.

Visibilités : les annonces ne sont que publiées ; la sonothèque passe par le filtre d'écoute de
l'utilisateur (``listenable_tracks``) ; les prêtres (connecté seulement) sont les clercs vérifiés
joignables par la messagerie, avec leur nom et leur office, jamais leur e-mail ni leur téléphone.
Pagination par type : ``offset`` et ``limit`` s'appliquent à chaque type demandé.
"""

from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank, TrigramWordSimilarity
from django.db.models import F, FloatField, Q, QuerySet
from django.db.models.functions import Cast
from django.utils import timezone

from apps.hierarchy.enums import AssignmentStatus, EtatDeVie, NodeStatus, StatutVerification

TYPES = ("bible", "paroisses", "lieux", "annonces", "pretres", "audio")
PARISH_TYPES = ("paroisse", "quasi_paroisse", "aumonerie")
MIN_LENGTH = 2
BIBLE_MIN_LENGTH = 3
MAX_OFFSET = 200


def _page(qs: QuerySet[Any] | list[Any], *, offset: int, limit: int) -> tuple[list[Any], bool]:
    rows = list(qs[offset : offset + limit + 1])
    return rows[:limit], len(rows) > limit


def search_bible(*, q: str, offset: int, limit: int, user: Any) -> tuple[list[dict[str, Any]], bool]:
    from apps.bible.services.search_service import SearchService

    if len(q) < BIBLE_MIN_LENGTH:
        return [], False
    rows = SearchService().verses(q, limit=offset + limit + 1, source_file=settings.BIBLE_EDITION or None)
    items = [
        {
            "id": r["id"],
            "book_name": r["book_name"],
            "book_slug": r["book_slug"],
            "chapter": r["chapter_number"],
            "verse": r["verse_number"],
            "text": r["text"],
        }
        for r in rows
    ]
    return _page(items, offset=offset, limit=limit)


def search_parishes(*, q: str, offset: int, limit: int, user: Any) -> tuple[list[dict[str, Any]], bool]:
    from apps.hierarchy.models import Node

    qs = (
        Node.objects.filter(type__code__in=PARISH_TYPES)
        .exclude(status=NodeStatus.SUPPRIME)
        .filter(Q(name__unaccent__icontains=q) | Q(city__unaccent__icontains=q) | Q(code__iexact=q))
        .select_related("type")
        .order_by("name")
    )
    rows, more = _page(qs, offset=offset, limit=limit)
    return [
        {"id": str(n.pk), "code": n.code, "name": n.name, "type": n.type.code, "city": n.city, "on_platform": n.is_active_on_platform}
        for n in rows
    ], more


def search_places(*, q: str, offset: int, limit: int, user: Any) -> tuple[list[dict[str, Any]], bool]:
    from apps.hierarchy.models import PlaceOfWorship

    qs = (
        PlaceOfWorship.objects.filter(is_active=True)
        .exclude(node__status=NodeStatus.SUPPRIME)
        .filter(Q(name__unaccent__icontains=q) | Q(city__unaccent__icontains=q))
        .select_related("node")
        .order_by("name", "pk")
    )
    rows, more = _page(qs, offset=offset, limit=limit)
    return [
        {"id": p.pk, "name": p.name, "kind": p.kind, "city": p.city, "node_id": str(p.node_id), "node_name": p.node.name}
        for p in rows
    ], more


def search_news(*, q: str, offset: int, limit: int, user: Any) -> tuple[list[dict[str, Any]], bool]:
    from apps.news.models import Article

    qs = (
        Article.objects.filter(status=Article.Status.PUBLISHED)
        .filter(Q(title__unaccent__icontains=q) | Q(excerpt__unaccent__icontains=q) | Q(content__unaccent__icontains=q))
        .select_related("scope_node")
        .order_by("-published_at", "pk")
    )
    rows, more = _page(qs, offset=offset, limit=limit)
    return [
        {
            "id": str(a.pk),
            "title": a.title,
            "excerpt": a.excerpt,
            "content_type": a.content_type,
            "published_at": a.published_at,
            "node_id": str(a.scope_node_id) if a.scope_node_id else None,
            "node_name": a.scope_node.name if a.scope_node else None,
        }
        for a in rows
    ], more


def search_priests(*, q: str, offset: int, limit: int, user: Any) -> tuple[list[dict[str, Any]], bool]:
    from apps.hierarchy.models import OfficeAssignment
    from apps.hierarchy.persons import full_name
    from apps.messaging.models import MessagingAvailability

    if not getattr(user, "is_authenticated", False):
        return [], False
    today = timezone.localdate()
    not_accepting = MessagingAvailability.objects.filter(accepts_new_conversations=False).values("user_id")
    qs = (
        OfficeAssignment.objects.filter(
            status=AssignmentStatus.ACTIVE,
            start_date__lte=today,
            office_type__capabilities__code="messagerie.recevoir_fideles",
            person__is_active=True,
            person__etat_de_vie=EtatDeVie.CLERC,
            person__statut_verification=StatutVerification.VERIFIE,
        )
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=today))
        .exclude(person_id__in=not_accepting)
        .exclude(person_id=user.pk)
        .filter(
            Q(person__profile__first_name__unaccent__icontains=q)
            | Q(person__profile__last_name__unaccent__icontains=q)
            | Q(node__name__unaccent__icontains=q)
        )
        .select_related("person__profile", "node", "office_type")
        .order_by("person__profile__last_name", "person__profile__first_name", "person_id", "start_date")
        .distinct("person__profile__last_name", "person__profile__first_name", "person_id")
    )
    rows, more = _page(qs, offset=offset, limit=limit)
    items = []
    for a in rows:
        name = full_name(a.person)
        if name:  # sans nom renseigné, la personne n'apparaît pas (son e-mail n'est jamais exposé)
            items.append(
                {"id": str(a.person_id), "name": name, "office": a.title, "node_id": str(a.node_id), "node_name": a.node.name}
            )
    return items, more


def search_audio(*, q: str, offset: int, limit: int, user: Any) -> tuple[list[dict[str, Any]], bool]:
    from apps.audio import access

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
        .order_by("-rank", "-play_count", "pk")
    )
    rows, more = _page(qs, offset=offset, limit=limit)
    return [
        {
            "id": str(t.pk),
            "title": t.title,
            "duration_seconds": t.duration_seconds,
            "source_name": t.source.name,
            "album_id": str(t.album_id) if t.album_id else None,
            "album_title": t.album.title if t.album else None,
        }
        for t in rows
    ], more


SEARCHERS: dict[str, Callable[..., tuple[list[dict[str, Any]], bool]]] = {
    "bible": search_bible,
    "paroisses": search_parishes,
    "lieux": search_places,
    "annonces": search_news,
    "pretres": search_priests,
    "audio": search_audio,
}


def search(*, user: Any, q: str, types: list[str], offset: int = 0, limit: int = 5) -> dict[str, Any]:
    q = " ".join((q or "").split())[:200]
    results: dict[str, Any] = {}
    for kind in types:
        items, more = SEARCHERS[kind](q=q, offset=offset, limit=limit, user=user)
        results[kind] = {"items": items, "next_offset": offset + limit if more else None}
    return {"q": q, "results": results}
