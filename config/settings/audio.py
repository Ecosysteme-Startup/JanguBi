"""Sonothèque paroissiale (plan suite V2, §5). Aucun secret en dur.

Chemins dans le stockage objet (bucket privé ; le CDN lit ``audio-hls/``) :
- ``audio-raw/<fichier>`` : fichier source téléversé, gardé pour réencoder ;
- ``audio-hls/<track_id>/<version>/`` : HLS (3 débits), MP3 de secours, forme d'onde. Immuable.
"""

from config.env import env

# --- Upload ----------------------------------------------------------------------------------
AUDIO_UPLOAD_MAX_SIZE = env.int("AUDIO_UPLOAD_MAX_SIZE", default=500 * 1024 * 1024)  # 500 Mo
# Durée de validité du POST présigné : un fichier de 500 Mo en 3G met du temps à partir.
AUDIO_UPLOAD_PRESIGNED_EXPIRY = env.int("AUDIO_UPLOAD_PRESIGNED_EXPIRY", default=3600)
# Liste blanche (type MIME → extensions). Les navigateurs annoncent plusieurs variantes.
AUDIO_UPLOAD_ALLOWED_TYPES: dict[str, tuple[str, ...]] = {
    "audio/mpeg": (".mp3",),
    "audio/mp3": (".mp3",),
    "audio/mp4": (".m4a",),
    "audio/x-m4a": (".m4a",),
    "audio/aac": (".aac", ".m4a"),
    "audio/x-aac": (".aac",),
    "audio/wav": (".wav",),
    "audio/x-wav": (".wav",),
    "audio/wave": (".wav",),
    "audio/flac": (".flac",),
    "audio/x-flac": (".flac",),
    "audio/ogg": (".ogg", ".opus"),
    "audio/opus": (".opus",),
}
AUDIO_RAW_PREFIX = env.str("AUDIO_RAW_PREFIX", default="audio-raw")
AUDIO_HLS_PREFIX = env.str("AUDIO_HLS_PREFIX", default="audio-hls")

# --- Encodage (worker ffmpeg, file Celery « media ») -----------------------------------------
AUDIO_FFMPEG_BIN = env.str("AUDIO_FFMPEG_BIN", default="ffmpeg")
AUDIO_FFPROBE_BIN = env.str("AUDIO_FFPROBE_BIN", default="ffprobe")
AUDIO_LOUDNORM_I = env.float("AUDIO_LOUDNORM_I", default=-16.0)  # EBU R128, LUFS
AUDIO_LOUDNORM_TP = env.float("AUDIO_LOUDNORM_TP", default=-1.5)
AUDIO_LOUDNORM_LRA = env.float("AUDIO_LOUDNORM_LRA", default=11.0)
AUDIO_HLS_SEGMENT_SECONDS = env.int("AUDIO_HLS_SEGMENT_SECONDS", default=6)
AUDIO_WAVEFORM_PEAKS = 200
AUDIO_TRANSCODE_MAX_RETRIES = 3
AUDIO_TRANSCODE_LOCK_SECONDS = env.int("AUDIO_TRANSCODE_LOCK_SECONDS", default=1800)
# Durée maximale d'un enregistrement (une retraite entière : 4 h).
AUDIO_MAX_DURATION_SECONDS = env.int("AUDIO_MAX_DURATION_SECONDS", default=4 * 3600)

# --- Lecture : URL signée du CDN (style Cloudflare « ?verify=<exp>-<sig> ») ------------------
# Vide : pas de CDN (dev) → URL MinIO présignée (S3) ou URL du média local.
AUDIO_CDN_BASE_URL = env.str("AUDIO_CDN_BASE_URL", default="")
# Secret HMAC partagé avec le Worker Cloudflare. Obligatoire dès que AUDIO_CDN_BASE_URL est défini.
AUDIO_CDN_SIGNING_SECRET = env.str("AUDIO_CDN_SIGNING_SECRET", default="")
AUDIO_SIGNED_URL_TTL_SECONDS = env.int("AUDIO_SIGNED_URL_TTL_SECONDS", default=6 * 3600)

# --- Cache applicatif (Redis) ----------------------------------------------------------------
AUDIO_CATALOG_CACHE_SECONDS = env.int("AUDIO_CATALOG_CACHE_SECONDS", default=600)  # 10 min
AUDIO_AUTHZ_CACHE_SECONDS = env.int("AUDIO_AUTHZ_CACHE_SECONDS", default=300)  # 5 min

# --- Reprise et synchronisation multi-appareils ----------------------------------------------
# L'horodatage client est borné : au plus tard « maintenant », au plus tôt « maintenant − 24 h ».
AUDIO_PLAYBACK_MAX_CLIENT_LAG_SECONDS = env.int("AUDIO_PLAYBACK_MAX_CLIENT_LAG_SECONDS", default=24 * 3600)

# --- Événements d'écoute (table partitionnée par mois) ---------------------------------------
AUDIO_EVENTS_MAX_BATCH = 100
AUDIO_EVENTS_MAX_AGE_DAYS = env.int("AUDIO_EVENTS_MAX_AGE_DAYS", default=7)  # rattrapage hors ligne
AUDIO_EVENTS_MAX_FUTURE_SECONDS = env.int("AUDIO_EVENTS_MAX_FUTURE_SECONDS", default=300)
AUDIO_EVENTS_RETENTION_MONTHS = env.int("AUDIO_EVENTS_RETENTION_MONTHS", default=13)
AUDIO_EVENTS_PARTITIONS_AHEAD = 2  # mois créés d'avance

# --- Recommandations (précalculées chaque nuit, file Celery « reco ») ------------------------
AUDIO_RECO_ENABLED = env.bool("AUDIO_RECO_ENABLED", default=True)  # interrupteur global
AUDIO_RECO_WINDOW_DAYS = env.int("AUDIO_RECO_WINDOW_DAYS", default=90)
AUDIO_RECO_NEIGHBORS = 50
AUDIO_RECO_MIN_CO_LISTENERS = env.int("AUDIO_RECO_MIN_CO_LISTENERS", default=2)
AUDIO_RECO_PER_USER = 100
AUDIO_RECO_COMPLETE_RATIO = 0.7  # écoute complète : plus de 70 % de la durée
AUDIO_RECO_SKIP_SECONDS = 30  # passe : moins de 30 s

# --- Files Celery ------------------------------------------------------------------------------
# Les tâches déclarent aussi leur file (``@shared_task(queue=...)``) : ce routage reste valable
# si un autre lot déclare les files globales (default, media, reco). On fusionne avec des routes
# déjà définies dans config/settings/celery.py au lieu de les écraser.
AUDIO_CELERY_TASK_ROUTES = {
    "apps.audio.tasks.audio_transcode_task": {"queue": "media"},
    "apps.audio.tasks.audio_reco_recompute_task": {"queue": "reco"},
}
from config.settings import celery as _celery_settings  # noqa: E402

_existing_routes = getattr(_celery_settings, "CELERY_TASK_ROUTES", None)
CELERY_TASK_ROUTES = {**(_existing_routes if isinstance(_existing_routes, dict) else {}), **AUDIO_CELERY_TASK_ROUTES}
