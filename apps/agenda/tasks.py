from celery import shared_task


@shared_task
def event_reminders_task() -> int:
    """Rappel la veille aux inscrits (EF-PAROI-08)."""
    from apps.agenda.services import event_reminders_send  # import local (HackSoft)

    return event_reminders_send()
