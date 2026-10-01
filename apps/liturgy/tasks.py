import logging
from datetime import date, timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="apps.liturgy.tasks.daily_sync",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=1800,
    max_retries=3,
)
def daily_sync_task(self, date_str: str | None = None, zones: list[str] | None = None):
    """Synchronise les données AELF du jour pour chaque zone.

    `async_to_sync` et NON `asyncio.run` : sous un worker gevent/eventlet (le cas
    avec Channels), une boucle d'événements tourne déjà dans le thread et
    `asyncio.run` lève `RuntimeError: This event loop is already running`.

    Les échecs par zone sont collectés puis relevés en fin de tâche : une zone en
    erreur n'empêche pas les autres de se synchroniser, mais l'indisponibilité
    d'AELF fait bien échouer la tâche (donc retry avec backoff) au lieu d'être
    avalée dans un log — sinon les fidèles n'ont pas les lectures du lendemain.
    """
    from asgiref.sync import async_to_sync

    from apps.liturgy.services import AelfService  # local import — évite les imports circulaires

    if not date_str:
        date_str = timezone.now().date().isoformat()

    if not zones:
        # DOIT correspondre à la zone lue par les APIs (défaut "afrique" dans
        # apps/liturgy/apis.py). Avec "romain" seul, le cache nocturne n'était
        # jamais utilisé : chaque requête retombait sur un fetch AELF live
        # (9 appels HTTP, retries 5×15 s) dans le cycle requête → lenteur/500.
        zones = [settings.LITURGY_ZONE]

    logger.info(f"Starting scheduled daily AELF sync for dates: {date_str} in zones: {zones}")

    failed_zones: list[str] = []

    for zone in zones:
        try:
            async_to_sync(AelfService.sync_daily_data)(date_str, zone)
        except Exception as e:
            logger.error(f"Failed to sync daily data for {date_str} ({zone}): {str(e)}")
            failed_zones.append(zone)

    if failed_zones:
        raise RuntimeError(f"AELF sync failed for {date_str} on zones: {', '.join(failed_zones)}")


@shared_task(name="apps.liturgy.tasks.bulk_import")
def bulk_import_task(start_date_str: str, end_date_str: str, zones: list[str] | None = None):
    """
    Backfills AELF data over a range of dates.
    In production, this could enqueue individual `daily_sync_task` to parallelize work.
    """
    try:
        start_dt = date.fromisoformat(start_date_str)
        end_dt = date.fromisoformat(end_date_str)
    except ValueError:
        logger.error("Invalid date format. Use YYYY-MM-DD.")
        return

    if not zones:
        zones = ["romain", "afrique"]

    logger.info(f"Starting bulk AELF sync from {start_date_str} to {end_date_str}")

    delta = timedelta(days=1)
    current_dt = start_dt

    while current_dt <= end_dt:
        dt_str = current_dt.isoformat()
        logger.info(f"Enqueuing daily sync for {dt_str}")

        # Dispatch to queue to avoid a single massive blocking task
        daily_sync_task.delay(dt_str, zones)

        current_dt += delta
