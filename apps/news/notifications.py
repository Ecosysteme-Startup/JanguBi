"""Notification des fidèles à la publication d'une annonce (EF-PAROI-08)."""


def article_published_notify(*, article_id: str) -> None:
    """Appelé après commit : la diffusion (potentiellement des milliers de fidèles) part en tâche."""
    from apps.news.tasks import article_published_notify_task

    article_published_notify_task.delay(article_id)
