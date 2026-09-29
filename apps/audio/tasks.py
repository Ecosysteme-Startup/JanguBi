"""Tâches Celery de la sonothèque. Import des services dans le corps des fonctions (HackSoft).

Files : ``media`` pour l'encodage (worker ffmpeg séparé), ``reco`` pour le calcul nocturne. Le
routage est aussi déclaré dans ``config/settings/audio.py`` (``CELERY_TASK_ROUTES``).
"""

from typing import Any

from celery import shared_task
from django.conf import settings


@shared_task(bind=True, queue="media", max_retries=3, acks_late=True)
def audio_transcode_task(self: Any, track_id: str, version: int) -> str:
    """Encode une version de piste. Idempotente (verrou + version) ; 3 nouvelles tentatives sur
    erreur technique, puis la piste passe en ``echec`` et l'uploader est prévenu."""
    from apps.audio.services import transcode_track

    final = self.request.retries >= min(self.max_retries, settings.AUDIO_TRANSCODE_MAX_RETRIES)
    try:
        return transcode_track(track_id=track_id, version=version, final_attempt=final)
    except Exception as exc:  # noqa: BLE001 - la piste est déjà remise « en_file » par le service
        raise self.retry(exc=exc, countdown=30 * (2**self.request.retries)) from exc


@shared_task(queue="reco")
def audio_reco_recompute_task() -> dict[str, Any]:
    """Chaque nuit (3 h) : voisins de co-écoute et de contenu, recommandations par utilisateur."""
    from apps.audio.recommendations import recompute_all

    return recompute_all()


@shared_task
def audio_play_event_partitions_task() -> dict[str, list[str]]:
    """Le 1er du mois : partitions des événements d'écoute créées d'avance, purge après 13 mois."""
    from apps.audio.services import play_event_partitions_ensure

    return play_event_partitions_ensure()
