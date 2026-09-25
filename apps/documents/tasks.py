from celery import shared_task


@shared_task
def document_requests_auto_escalate() -> int:
    """Relances quotidiennes selon les délais du nœud (EF-ACT-08)."""
    from apps.documents.services import document_requests_remind  # import local (HackSoft)

    return document_requests_remind()


@shared_task
def document_attachments_purge_task() -> int:
    """Pièces justificatives supprimées 90 jours après la clôture (RG-12, EF-ACT-09)."""
    from apps.documents.services import document_attachments_purge

    return document_attachments_purge()
