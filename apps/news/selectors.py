"""Lectures des annonces et articles V1 (SRS §3.5)."""

import datetime
from typing import Any

from django.db.models import Count, Exists, IntegerField, OuterRef, Q, QuerySet, Subquery, Value
from django.db.models.functions import Coalesce

from apps.core.exceptions import NotFoundError, PermissionDeniedError
from apps.hierarchy import authz
from apps.hierarchy.models import Node
from apps.hierarchy.selectors import node_ancestors
from apps.news.models import Article, ArticleCategory, ArticleReaction, ArticleRead

_BASE_RELATED = ("category", "author", "author__profile", "scope_node", "scope_node__type", "scope_place", "cover_image")


def category_list(*, active_only: bool = True) -> QuerySet[ArticleCategory]:
    qs = ArticleCategory.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.order_by("display_order", "name")


def category_get(*, category_id: int) -> ArticleCategory:
    try:
        return ArticleCategory.objects.get(pk=category_id, is_active=True)
    except ArticleCategory.DoesNotExist as exc:
        raise NotFoundError("Catégorie introuvable.", {"category_id": category_id}) from exc


def _reaction_count(reaction_type: str) -> Coalesce:
    counts = (
        ArticleReaction.objects.filter(article=OuterRef("pk"), reaction_type=reaction_type)
        .order_by()
        .values("article")
        .annotate(n=Count("pk"))
        .values("n")
    )
    return Coalesce(Subquery(counts, output_field=IntegerField()), Value(0))


def annotate_reactions(qs: QuerySet[Article], *, viewer: Any = None) -> QuerySet[Article]:
    """Compteurs par type de réaction et réactions du lecteur, en sous-requêtes (pas de N+1)."""
    annotations: dict[str, Any] = {f"reactions_{t}": _reaction_count(t) for t in ArticleReaction.ReactionType.values}
    if viewer is not None and getattr(viewer, "is_authenticated", False):
        for t in ArticleReaction.ReactionType.values:
            annotations[f"mine_{t}"] = Exists(
                ArticleReaction.objects.filter(article=OuterRef("pk"), user=viewer, reaction_type=t)
            )
    return qs.annotate(**annotations)


def article_list_published(
    *,
    node: Node | None = None,
    sunday: datetime.date | None = None,
    content_type: str | None = None,
    category_id: int | None = None,
    viewer: Any = None,
) -> QuerySet[Article]:
    """Contenus publiés, publics (EF-PAROI-01, -02). ``node`` : ce nœud et son sous-arbre."""
    qs = Article.objects.filter(status=Article.Status.PUBLISHED).select_related(*_BASE_RELATED)
    if node is not None:
        qs = qs.filter(scope_node__path__startswith=node.path)
    if sunday is not None:
        qs = qs.filter(is_sunday_notice=True, sunday_date=sunday)
    if content_type:
        qs = qs.filter(content_type=content_type)
    if category_id:
        qs = qs.filter(category_id=category_id)
    return annotate_reactions(qs, viewer=viewer).order_by("-published_at")


def article_get_published(*, article_id: Any, viewer: Any = None) -> Article:
    qs = annotate_reactions(
        Article.objects.filter(status=Article.Status.PUBLISHED).select_related(*_BASE_RELATED), viewer=viewer
    )
    try:
        return qs.get(pk=article_id)
    except (Article.DoesNotExist, ValueError) as exc:
        raise NotFoundError("Article introuvable.", {"article_id": str(article_id)}) from exc


def feed_for(*, user: Any) -> QuerySet[Article]:
    """Flux du fidèle (EF-PAROI-04) : global + paroisse suivie et ses ancêtres (diocèse…)."""
    scope = Q(scope_node__isnull=True)
    parish = getattr(user, "paroisse_suivie", None)
    if parish is not None:
        lineage = [parish.pk, *node_ancestors(node=parish).values_list("pk", flat=True)]
        scope |= Q(scope_node_id__in=lineage)
    qs = Article.objects.filter(scope, status=Article.Status.PUBLISHED).select_related(*_BASE_RELATED)
    return annotate_reactions(qs, viewer=user).order_by("-published_at")


# --- Staff ----------------------------------------------------------------------------------


def article_list_for_staff(*, user: Any, filters: dict[str, Any] | None = None) -> QuerySet[Article]:
    """Tous statuts, sur les nœuds où ``user`` a ``annonces.publier`` (+ global pour la plateforme)."""
    filters = filters or {}
    allowed = authz.noeuds_autorises(user, "annonces.publier")
    scope = Q(scope_node__in=allowed)
    if authz.peut(user, "plateforme.admin", None):
        scope |= Q(scope_node__isnull=True)
    qs = Article.objects.filter(scope).select_related(*_BASE_RELATED).annotate(reads_count=Count("reads", distinct=True))
    if node_id := filters.get("node"):
        node = Node.objects.filter(pk=node_id).first()
        if node is None:
            raise NotFoundError("Nœud introuvable.", {"node_id": str(node_id)})
        qs = qs.filter(scope_node__path__startswith=node.path)
    if status := filters.get("status"):
        qs = qs.filter(status=status)
    if content_type := filters.get("type"):
        qs = qs.filter(content_type=content_type)
    if place_id := filters.get("place"):
        qs = qs.filter(scope_place_id=place_id)
    if query := (filters.get("q") or "").strip():
        qs = qs.filter(Q(title__icontains=query) | Q(content__icontains=query) | Q(excerpt__icontains=query))
    return qs.order_by("-created_at")


def article_get_for_staff(*, user: Any, article_id: Any) -> Article:
    """404 (et non 403) hors de la portée : on ne révèle pas l'existence d'un brouillon."""
    try:
        return article_list_for_staff(user=user).get(pk=article_id)
    except (Article.DoesNotExist, ValueError) as exc:
        raise NotFoundError("Article introuvable.", {"article_id": str(article_id)}) from exc


def article_reads_count(*, article: Article) -> int:
    return ArticleRead.objects.filter(article=article).count()


def next_sunday(*, today: datetime.date) -> datetime.date:
    """Le dimanche à venir (aujourd'hui si l'on est dimanche)."""
    return today + datetime.timedelta(days=(6 - today.weekday()) % 7)


def sunday_sheet(*, user: Any, node: Node, sunday: datetime.date) -> dict[str, Any]:
    """Feuille d'annonces lue à la fin des messes d'un dimanche (EF-PAROI-02).

    Annonces du dimanche du nœud et de son sous-arbre (publiées ou programmées : la feuille
    s'imprime souvent la veille), suivies de celles, publiées, des nœuds parents (diocèse…).
    Réservée à qui peut publier sur le nœud (elle contient des annonces non encore publiées)."""
    if not authz.peut(user, "annonces.publier", node):
        raise PermissionDeniedError(
            "Vous ne pouvez pas éditer la feuille d'annonces de ce nœud.", code="publish_forbidden"
        )
    base = (
        Article.objects.filter(is_sunday_notice=True, sunday_date=sunday)
        .select_related("scope_node", "scope_place", "category", "author", "author__profile")
        .order_by("scope_node__depth", "scope_place__name", "published_at", "created_at")
    )
    own = base.filter(
        scope_node__path__startswith=node.path,
        status__in=(Article.Status.PUBLISHED, Article.Status.SCHEDULED),
    )
    ancestors = base.filter(scope_node__in=node_ancestors(node=node), status=Article.Status.PUBLISHED)
    return {"node": node, "sunday": sunday, "items": list(own) + list(ancestors)}
