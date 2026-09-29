from config.env import env

# https://docs.celeryproject.org/en/stable/userguide/configuration.html

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="amqp://guest:guest@localhost//")
CELERY_RESULT_BACKEND = "django-db"

# Désactiver les heartbeats pour éviter "Too many heartbeats missed"
# lors des tâches longues et bloquantes (ex: import Bible) sur un worker mono-thread
CELERY_BROKER_HEARTBEAT = 0

CELERY_TIMEZONE = "UTC"

CELERY_TASK_SOFT_TIME_LIMIT = 1200  # 20 minutes
CELERY_TASK_TIME_LIMIT = 1800  # 30 minutes
CELERY_TASK_MAX_RETRIES = 3

# --- Files séparées (plan V2 §2 ligne 7 et §3 point 5, lot B2) ---------------------------------
# « default » : e-mails, notifications, push, webhooks, tâches courtes.
# « media »   : encodage audio ffmpeg (lot B3), worker dédié à faible concurrence (1-2).
# « reco »    : recommandations précalculées (lots B3/B4), calculs longs de nuit.
# Un encodage de 60 s ne doit jamais retarder un e-mail de confirmation.
# Déclarer une tâche dans une file : nom de module (routes ci-dessous) ou
# ``@shared_task(queue="media")``. Workers : Procfile et docker-compose.yml ; le worker
# par défaut lit aussi l'ancienne file « celery » (messages en attente au déploiement).
from kombu import Exchange, Queue  # noqa: E402

CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_DEFAULT_EXCHANGE = "default"
CELERY_TASK_DEFAULT_ROUTING_KEY = "default"
CELERY_TASK_QUEUES = (
    Queue("default", Exchange("default"), routing_key="default"),
    Queue("media", Exchange("media"), routing_key="media"),
    Queue("reco", Exchange("reco"), routing_key="reco"),
)
# Motifs fnmatch sur le nom complet de la tâche (« * » traverse les points). Une file posée
# dans le décorateur (``queue=``) l'emporte sur ces routes.
CELERY_TASK_ROUTES = {
    # Encodage et traitement des médias (B3) : ex. apps.audio.tasks.audio_transcode_task.
    "apps.*.tasks_media.*": {"queue": "media"},
    "apps.*.tasks.media_*": {"queue": "media"},
    "apps.*.tasks.*transcode*": {"queue": "media"},
    # Recommandations (B3, B4) : ex. apps.bible.tasks.bible_reco_recompute_task.
    "apps.*.tasks_reco.*": {"queue": "reco"},
    "apps.*.tasks.reco_*": {"queue": "reco"},
    "apps.*.tasks.*_reco_*": {"queue": "reco"},
}
# Une tâche longue ne réserve pas d'avance les messages des autres (worker media en --prefetch-multiplier=1).
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
