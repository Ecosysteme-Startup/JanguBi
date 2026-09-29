"""Temps réel et exploitation (lot B2) : présence, SSE, push, métriques. Aucun secret en dur.

Protocole des clients : docs/TEMPS-REEL.md. Exploitation et seuils : docs/SCALING.md.
"""

from config.env import env

# --- Présence (messagerie) ------------------------------------------------------------------
# Compteur de connexions par personne dans le cache (Redis en production) : la clé expire
# après PRESENCE_TTL_SECONDS sans battement ; le client envoie {"type": "presence.ping"}
# toutes les PRESENCE_PING_SECONDS.
PRESENCE_CACHE_ALIAS = env.str("PRESENCE_CACHE_ALIAS", default="default")
PRESENCE_TTL_SECONDS = env.int("PRESENCE_TTL_SECONDS", default=60)
PRESENCE_PING_SECONDS = env.int("PRESENCE_PING_SECONDS", default=25)
PRESENCE_MAX_USERS_PER_QUERY = env.int("PRESENCE_MAX_USERS_PER_QUERY", default=50)

# --- SSE (text/event-stream, Daphne en ASGI) ------------------------------------------------
SSE_HEARTBEAT_SECONDS = env.float("SSE_HEARTBEAT_SECONDS", default=15.0)
SSE_RETRY_MILLISECONDS = env.int("SSE_RETRY_MILLISECONDS", default=5000)
# Tampon de reprise (Last-Event-ID) : derniers événements gardés par flux, et leur durée de vie.
SSE_REPLAY_SIZE = env.int("SSE_REPLAY_SIZE", default=50)
SSE_REPLAY_TTL_SECONDS = env.int("SSE_REPLAY_TTL_SECONDS", default=600)
# Durée maximale d'une connexion : le client se reconnecte seul (retry), ce qui recharge les droits.
SSE_MAX_CONNECTION_SECONDS = env.int("SSE_MAX_CONNECTION_SECONDS", default=30 * 60)

# --- Push (FCM HTTP v1 et APNs) --------------------------------------------------------------
PUSH_ENABLED = env.bool("PUSH_ENABLED", default=False)
PUSH_HTTP_TIMEOUT_SECONDS = env.float("PUSH_HTTP_TIMEOUT_SECONDS", default=10.0)
# FCM : identifiant du projet Firebase et compte de service (JSON en clair ou chemin d'un fichier).
FCM_PROJECT_ID = env.str("FCM_PROJECT_ID", default="")
FCM_SERVICE_ACCOUNT_JSON = env.str("FCM_SERVICE_ACCOUNT_JSON", default="")
FCM_SERVICE_ACCOUNT_FILE = env.str("FCM_SERVICE_ACCOUNT_FILE", default="")
FCM_ANDROID_CHANNEL_ID = env.str("FCM_ANDROID_CHANNEL_ID", default="jangubi-default")
# APNs : authentification par jeton (clé .p8), HTTP/2.
APNS_TEAM_ID = env.str("APNS_TEAM_ID", default="")
APNS_KEY_ID = env.str("APNS_KEY_ID", default="")
APNS_PRIVATE_KEY = env.str("APNS_PRIVATE_KEY", default="", multiline=True)
APNS_PRIVATE_KEY_FILE = env.str("APNS_PRIVATE_KEY_FILE", default="")
APNS_TOPIC = env.str("APNS_TOPIC", default="sn.numerisen.jangubi")
APNS_USE_SANDBOX = env.bool("APNS_USE_SANDBOX", default=False)

# --- Métriques Prometheus ---------------------------------------------------------------------
# /metrics : adresse du collecteur dans la liste (REMOTE_ADDR, jamais X-Forwarded-For) OU jeton
# « Authorization: Bearer <METRICS_TOKEN> ». Une requête passée par le proxy public
# (X-Forwarded-For présent) exige le jeton.
METRICS_ENABLED = env.bool("METRICS_ENABLED", default=True)
METRICS_ALLOWED_CIDRS = env.list("METRICS_ALLOWED_CIDRS", default=["127.0.0.1/32", "::1/128"])
METRICS_TOKEN = env.str("METRICS_TOKEN", default="")
