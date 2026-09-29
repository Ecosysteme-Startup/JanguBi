from celery import shared_task


@shared_task
def assignments_sync_task() -> dict[str, int]:
    """Active et termine les nominations selon leurs dates (EF-PER-06), chaque nuit."""
    from apps.hierarchy.services_offices import assignments_sync_statuses  # import local (HackSoft)

    return assignments_sync_statuses()
