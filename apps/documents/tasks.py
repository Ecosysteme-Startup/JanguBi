from celery import shared_task


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def document_requests_auto_escalate(self) -> int:
    """Relances quotidiennes selon les délais du nœud (EF-ACT-08)."""
    from apps.documents.services import document_requests_remind  # import local (HackSoft)

    try:
        return document_requests_remind()
    except Exception as exc:  # noqa: BLE001 — incident d'infrastructure : on retente
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def document_attachments_purge_task(self) -> int:
    """Pièces justificatives supprimées 90 jours après la clôture (RG-12, EF-ACT-09)."""
    from apps.documents.services import document_attachments_purge

    try:
        return document_attachments_purge()
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc) from exc
