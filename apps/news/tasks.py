from celery import shared_task


@shared_task
def articles_publish_due_task() -> int:
    """Publie les annonces programmées arrivées à échéance (EF-PAROI-03)."""
    from apps.news.services import articles_publish_due  # import local (HackSoft)

    return articles_publish_due()


@shared_task
def article_published_notify_task(article_id: str) -> int:
    """Prévient les fidèles qui suivent la paroisse (ou une paroisse du sous-arbre) de l'annonce."""
    from apps.messaging.services_notifications import people_notify
    from apps.news.models import Article
    from apps.users.models import BaseUser

    article = Article.objects.select_related("scope_node").filter(pk=article_id, status="published").first()
    if article is None or article.scope_node is None:
        return 0  # contenu global : pas de diffusion massive
    followers = (
        BaseUser.objects.filter(is_active=True, paroisse_suivie__path__startswith=article.scope_node.path)
        .exclude(pk=article.author_id)
        .values_list("pk", flat=True)
    )
    return people_notify(
        user_ids=list(followers),
        topic="annonces",
        event_type="news.published",
        payload={"article_id": str(article.pk), "title": article.title, "node_name": article.scope_node.name},
        email_template="annonce_publiee",
        email_context={"title": article.title, "node_name": article.scope_node.name, "article_id": str(article.pk)},
    )
