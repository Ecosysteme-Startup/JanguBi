from celery import shared_task


@shared_task(autoretry_for=(Exception,), max_retries=5, retry_backoff=True)
def donations_webhook_process_task(event_id: int) -> str:
    """Traite une notification de l'agrégateur (contre-vérification du statut)."""
    from apps.donations.services import webhook_process  # import local (HackSoft)

    return webhook_process(event_id=event_id).status


@shared_task
def donations_reconcile_task() -> dict[str, int]:
    """Toutes les 10 minutes : paiements en attente relus, dépassements expirés."""
    from apps.donations.services import donations_reconcile  # import local (HackSoft)

    return donations_reconcile()


@shared_task
def donations_payouts_sync_task() -> int:
    """Chaque jour : reversements de l'agrégateur importés et rapprochés."""
    from apps.donations.services import payouts_sync  # import local (HackSoft)

    return payouts_sync()


@shared_task
def donations_donor_email_purge_task() -> int:
    """Chaque jour : adresses des dons sans compte effacées après 90 jours."""
    from apps.donations.services import donor_emails_purge  # import local (HackSoft)

    return donor_emails_purge()
