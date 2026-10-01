import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=600, max_retries=3)
def populate_tsv_task(self, book_id: int):
    """
    Creates/updates the tsvector column for a given book.
    """
    from apps.bible.services.index_service import IndexService

    try:
        IndexService.populate_tsv_for_book(book_id)
    except Exception as e:
        logger.error(f"Failed to populate TSV for book_id {book_id}: {e}")
        raise


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=1800, max_retries=3)
def fetch_aelf_daily(self):
    """
    Fetches the daily reading from AELF.

    `async_to_sync` et NON `asyncio.run` : sous un worker gevent/eventlet (le
    cas avec Channels), une boucle d'événements tourne déjà dans le thread et
    `asyncio.run` lève `RuntimeError: This event loop is already running` —
    le fetch nocturne échouerait silencieusement et les fidèles n'auraient pas
    les lectures du lendemain.
    """
    from asgiref.sync import async_to_sync

    from apps.bible.services.aelf_service import AELFService

    try:
        service = AELFService()
        async_to_sync(service.fetch_daily_readings)()
    except Exception as e:
        logger.error(f"Failed to fetch AELF readings: {e}")
        raise


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=600, max_retries=3)
def import_file_task(self, file_path: str, source: str):
    """
    Background job to import a JSON bible file.
    """
    from apps.bible.services.import_service import ImportService

    try:
        service = ImportService()
        service.import_file(file_path, source)
    except Exception as e:
        logger.error(f"Import failed for {file_path}: {str(e)}")
        raise


@shared_task(bind=True, queue="reco", acks_late=True, max_retries=1)
def bible_reco_recompute_task(self):
    """« Pour vous aujourd'hui » précalculé pour les fidèles actifs (plan V2 §6).

    File `reco` (plan §3.5) ; idempotente : une ligne par fidèle et par jour, réécrite si la
    tâche est livrée deux fois.
    """
    from apps.bible.services.recommendation_service import daily_recommendations_recompute

    return daily_recommendations_recompute()
