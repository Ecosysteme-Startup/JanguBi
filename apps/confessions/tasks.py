from celery import shared_task


@shared_task
def confession_slots_generate_task() -> int:
    """Prolonge chaque jour l'horizon de 4 semaines de créneaux."""
    from apps.confessions.services import slots_generate  # import local (HackSoft)

    return slots_generate()


@shared_task
def confession_reminders_task() -> int:
    """Rappels à J-1 et H-2."""
    from apps.confessions.services import bookings_remind  # import local (HackSoft)

    return bookings_remind()
