from celery import shared_task


@shared_task
def articles_publish_due_task() -> int:
    """Publie les annonces programmées arrivées à échéance (EF-PAROI-03)."""
    from apps.news.services import articles_publish_due  # import local (HackSoft)

    return articles_publish_due()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def article_published_notify_task(self, article_id: str) -> int:
    """Prévient les fidèles qui suivent la paroisse (ou une paroisse du sous-arbre) de l'annonce."""
    from apps.news.models import Article
    from apps.users.models import BaseUser

    article = Article.objects.select_related("scope_node").filter(pk=article_id, status="published").first()
    if article is None or article.scope_node is None:
        return 0  # contenu global : pas de diffusion massive
    followers = (
        BaseUser.objects.filter(is_active=True, paroisse_suivie__path__startswith=article.scope_node.path)
        .exclude(pk=article.author_id)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    payload = {"article_id": str(article.pk), "title": article.title, "node_name": article.scope_node.name}
    notified = 0
    # Par tranches : un diocèse peut compter des dizaines de milliers de fidèles.
    batch: list = []
    for user_id in followers.iterator(chunk_size=NOTIFY_BATCH_SIZE):
        batch.append(user_id)
        if len(batch) == NOTIFY_BATCH_SIZE:
            notified += _notify_batch(batch, payload, article)
            batch = []
    if batch:
        notified += _notify_batch(batch, payload, article)
    return notified


NOTIFY_BATCH_SIZE = 500


def _notify_batch(user_ids: list, payload: dict, article) -> int:
    from apps.messaging.services_notifications import people_notify

    return people_notify(
        user_ids=user_ids,
        topic="annonces",
        event_type="news.published",
        payload=payload,
        email_template="annonce_publiee",
        email_context={"title": article.title, "node_name": article.scope_node.name, "article_id": str(article.pk)},
    )
