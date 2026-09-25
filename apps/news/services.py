"""Annonces et articles de la V1 (SRS §3.5, lot L4).

Autorisation : ``annonces.publier`` sur le nœud de portée (ADR-003) ; la portée globale
(aucun nœud) est réservée à l'administration de la plateforme. Toute écriture passe par
ici ; les vues ne font que traduire HTTP.
"""

import datetime
import logging
from typing import Any

import nh3
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.hierarchy import authz
from apps.hierarchy.audit import audit_log
from apps.hierarchy.models import Node, PlaceOfWorship
from apps.news.models import Article, ArticleCategory, ArticleReaction, ArticleRead

logger = logging.getLogger(__name__)

# Types publiables en V1 : la lettre pastorale est gelée (ADR-006).
V1_CONTENT_TYPES = (Article.ContentType.ANNOUNCEMENT, Article.ContentType.ARTICLE)
UPDATABLE_FIELDS = (
    "title",
    "excerpt",
    "content",
    "content_format",
    "category",
    "cover_image",
    "is_sunday_notice",
    "sunday_date",
    "content_type",
)


# --- Autorisation --------------------------------------------------------------------------


def article_publish_check(*, user: Any, node: Node | None) -> None:
    if node is None:
        if not authz.peut(user, "plateforme.admin", None):
            raise PermissionDeniedError("Seule la plateforme publie des contenus globaux.", code="global_scope_forbidden")
        return
    if not authz.peut(user, "annonces.publier", node):
        raise PermissionDeniedError("Vous ne pouvez pas publier sur ce nœud.", code="publish_forbidden")


def _clean_content(content: str, content_format: str) -> str:
    """HTML de l'éditeur riche assaini AVANT persistance (nh3) ; le texte brut passe tel quel."""
    if content_format == Article.ContentFormat.HTML:
        return nh3.clean(content)
    return content


def _slug(title: str, node: Node | None) -> str:
    base = slugify(title)[:180] or "article"
    suffix = node.code.lower() if node is not None else "global"
    candidate = f"{base}-{suffix}"[:210]
    if not Article.objects.filter(slug=candidate).exists():
        return candidate
    return f"{candidate[:200]}-{Article.objects.filter(slug__startswith=candidate).count() + 1}"


def _sunday_check(*, is_sunday_notice: bool, sunday_date: datetime.date | None) -> None:
    if not is_sunday_notice:
        return
    if sunday_date is None:
        raise ApplicationError("Indiquez le dimanche concerné.", code="sunday_date_required")
    if sunday_date.weekday() != 6:
        raise ApplicationError("La date d'une annonce du dimanche doit être un dimanche.", code="sunday_date_invalid")


def _place_check(*, node: Node | None, place: PlaceOfWorship | None) -> None:
    if place is not None and (node is None or place.node_id != node.pk):
        raise ApplicationError("Le lieu de culte doit appartenir au nœud de l'annonce.", code="place_not_in_node")


# --- Écritures -----------------------------------------------------------------------------


@transaction.atomic
def article_create(
    *,
    author: Any,
    title: str,
    content: str,
    category: ArticleCategory,
    node: Node | None = None,
    place: PlaceOfWorship | None = None,
    content_type: str = Article.ContentType.ANNOUNCEMENT,
    content_format: str = Article.ContentFormat.TEXT,
    excerpt: str = "",
    cover_image: Any = None,
    is_sunday_notice: bool = False,
    sunday_date: datetime.date | None = None,
) -> Article:
    """Crée un brouillon. La publication est une étape distincte (immédiate ou programmée)."""
    article_publish_check(user=author, node=node)
    if content_type not in V1_CONTENT_TYPES:
        raise ApplicationError("Ce type de contenu n'est pas disponible en V1.", code="content_type_frozen")
    _place_check(node=node, place=place)
    _sunday_check(is_sunday_notice=is_sunday_notice, sunday_date=sunday_date)

    article = Article.objects.create(
        author=author,
        title=title,
        slug=_slug(title, node),
        excerpt=excerpt,
        content=_clean_content(content, content_format),
        content_format=content_format,
        content_type=content_type,
        category=category,
        cover_image=cover_image,
        scope_node=node,
        scope_place=place,
        # Ancienne colonne conservée jusqu'en L9 : cohérente pour les lecteurs historiques.
        scope_type=Article.ScopeType.GLOBAL if node is None else Article.ScopeType.PARISH,
        is_sunday_notice=is_sunday_notice,
        sunday_date=sunday_date,
        announcement_date=sunday_date,
        status=Article.Status.DRAFT,
    )
    audit_log(actor=author, action="annonce.creation", target=article, node=node)
    return article


@transaction.atomic
def article_update(*, article: Article, editor: Any, data: dict[str, Any]) -> Article:
    article_publish_check(user=editor, node=article.scope_node)
    unknown = set(data) - set(UPDATABLE_FIELDS)
    if unknown:
        raise ApplicationError("Champs non modifiables.", {"fields": sorted(unknown)}, code="field_not_updatable")
    if data.get("content_type", article.content_type) not in V1_CONTENT_TYPES:
        raise ApplicationError("Ce type de contenu n'est pas disponible en V1.", code="content_type_frozen")
    is_sunday = data.get("is_sunday_notice", article.is_sunday_notice)
    sunday_date = data.get("sunday_date", article.sunday_date)
    _sunday_check(is_sunday_notice=is_sunday, sunday_date=sunday_date)

    for field, value in data.items():
        setattr(article, field, value)
    if "content" in data or "content_format" in data:
        article.content = _clean_content(article.content, article.content_format)
    if "sunday_date" in data:
        article.announcement_date = article.sunday_date
    article.save()
    audit_log(actor=editor, action="annonce.modification", target=article, node=article.scope_node)
    return article


@transaction.atomic
def article_publish(*, article: Article, editor: Any, publish_at: datetime.datetime | None = None) -> Article:
    """Publie tout de suite, ou programme la publication (EF-PAROI-03)."""
    article_publish_check(user=editor, node=article.scope_node)
    # Relu sous verrou : la tâche de publication programmée peut agir en même temps.
    article = Article.objects.select_for_update(of=("self",)).select_related("scope_node").get(pk=article.pk)
    if article.status == Article.Status.PUBLISHED:
        raise ApplicationError("L'article est déjà publié.", code="already_published")
    now = timezone.now()
    if publish_at is not None and publish_at > now:
        article.status = Article.Status.SCHEDULED
        article.publish_at = publish_at
        article.save(update_fields=["status", "publish_at", "updated_at"])
        audit_log(actor=editor, action="annonce.programmation", target=article, node=article.scope_node)
        return article
    _publish_now(article=article, at=now)
    audit_log(actor=editor, action="annonce.publication", target=article, node=article.scope_node)
    return article


def _publish_now(*, article: Article, at: datetime.datetime) -> None:
    article.status = Article.Status.PUBLISHED
    article.published_at = at
    article.publish_at = None
    article.save(update_fields=["status", "published_at", "publish_at", "updated_at"])
    from apps.news.notifications import article_published_notify

    transaction.on_commit(lambda: article_published_notify(article_id=str(article.pk)))


def articles_publish_due(*, now: datetime.datetime | None = None) -> int:
    """Tâche Beat : publie les articles programmés arrivés à échéance.

    Un article par transaction : un article en erreur n'empêche pas la publication des autres
    (et un article publié ne repasse pas en « programmé » à cause d'un voisin)."""
    now = now or timezone.now()
    due_ids = list(
        Article.objects.filter(status=Article.Status.SCHEDULED, publish_at__lte=now).values_list("pk", flat=True)
    )
    count = 0
    for article_id in due_ids:
        try:
            with transaction.atomic():
                article = (
                    Article.objects.select_for_update(skip_locked=True)
                    .filter(pk=article_id, status=Article.Status.SCHEDULED)
                    .first()
                )
                if article is None:
                    continue
                _publish_now(article=article, at=article.publish_at or now)
                audit_log(actor=None, action="annonce.publication", target=article, node=article.scope_node)
                count += 1
        except Exception:  # noqa: BLE001 — journalisé, l'article sera repris au prochain passage
            logger.exception("news.publish_due_failed", extra={"article_id": str(article_id)})
    return count


@transaction.atomic
def article_unpublish(*, article: Article, editor: Any, reason: str = "") -> Article:
    article_publish_check(user=editor, node=article.scope_node)
    if article.status not in (Article.Status.PUBLISHED, Article.Status.SCHEDULED):
        raise ApplicationError("Seul un article publié ou programmé peut être retiré.", code="not_published")
    article.status = Article.Status.UNPUBLISHED
    article.unpublished_at = timezone.now()
    article.unpublished_by = editor
    article.unpublish_reason = reason
    article.publish_at = None
    article.save(
        update_fields=["status", "unpublished_at", "unpublished_by", "unpublish_reason", "publish_at", "updated_at"]
    )
    audit_log(actor=editor, action="annonce.retrait", target=article, node=article.scope_node)
    return article


@transaction.atomic
def article_delete(*, article: Article, editor: Any) -> None:
    article_publish_check(user=editor, node=article.scope_node)
    if article.status in (Article.Status.PUBLISHED, Article.Status.SCHEDULED):
        raise ApplicationError(
            "Un article publié ou programmé ne peut pas être supprimé. Retirez-le d'abord.", code="published"
        )
    audit_log(actor=editor, action="annonce.suppression", target=article, node=article.scope_node)
    article.delete()


@transaction.atomic
def article_mark_read(*, article: Article, user: Any) -> bool:
    """Une lecture par personne (EF-PAROI-05). Renvoie vrai si c'est la première."""
    if article.status != Article.Status.PUBLISHED:
        raise ApplicationError("Article introuvable.", code="not_found")
    try:
        with transaction.atomic():
            _, created = ArticleRead.objects.get_or_create(article=article, user=user)
    except IntegrityError:
        return False
    return created


@transaction.atomic
def article_reaction_set(*, article: Article, user: Any, reaction_type: str, active: bool) -> None:
    """Pose ou retire une réaction : un « set » idempotent, jamais une bascule."""
    if reaction_type not in ArticleReaction.ReactionType.values:
        raise ApplicationError("Type de réaction inconnu.", code="invalid_reaction")
    if article.status != Article.Status.PUBLISHED:
        raise ApplicationError("Article introuvable.", code="not_found")
    if active:
        ArticleReaction.objects.get_or_create(article=article, user=user, reaction_type=reaction_type)
    else:
        ArticleReaction.objects.filter(article=article, user=user, reaction_type=reaction_type).delete()
