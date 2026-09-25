from django.core.exceptions import ImproperlyConfigured

from config.env import env

from .base import *  # noqa

DEBUG = env.bool("DJANGO_DEBUG", default=False)

# Pas de MFA sur l'admin Django (revue de sécurité L9) : fermée sauf décision explicite.
DJANGO_ADMIN_ENABLED = env.bool("DJANGO_ADMIN_ENABLED", default=False)

import logging as _logging  # noqa: E402

if env.bool("LEGACY_JWT_ENABLED", default=True):
    _logging.getLogger(__name__).warning(
        "LEGACY_JWT_ENABLED=true : l'ancien JWT reste accepté (repli super-admin, jeton WebSocket "
        "dans l'URL). À désactiver dès la bascule du front sur Keycloak (ADR-004)."
    )

SECRET_KEY = env("SECRET_KEY")

# Chiffrement des conversations pastorales (apps/messaging/fields.py).
#
# En base, ce réglage retombe silencieusement sur SECRET_KEY faute de mieux.
# C'est acceptable en développement, mais dangereux en production : SECRET_KEY
# est un secret que l'on ROTE (fuite, départ d'un prestataire, hygiène). Le
# jour où on la roterait, toute la messagerie chiffrée deviendrait illisible —
# de façon définitive et silencieuse, sans erreur au démarrage, jusqu'à ce
# qu'un fidèle ouvre une conversation.
#
# On refuse donc de démarrer en production sans clé dédiée, et on refuse
# qu'elle soit égale à SECRET_KEY : mieux vaut un déploiement qui échoue tout
# de suite qu'un historique pastoral perdu plus tard.
MESSAGING_ENCRYPTION_KEY = env.str("MESSAGING_ENCRYPTION_KEY", default="")

if not MESSAGING_ENCRYPTION_KEY:
    raise ImproperlyConfigured(
        "MESSAGING_ENCRYPTION_KEY est obligatoire en production. Sans clé dédiée, "
        "les conversations sont chiffrées avec SECRET_KEY : toute rotation de "
        "celle-ci rendrait l'historique définitivement illisible. "
        "Générer : python -c \"import secrets; print(secrets.token_hex(32))\""
    )

if MESSAGING_ENCRYPTION_KEY == SECRET_KEY:
    raise ImproperlyConfigured(
        "MESSAGING_ENCRYPTION_KEY doit être DIFFÉRENTE de SECRET_KEY : la première "
        "ne doit jamais être rotée, la seconde doit pouvoir l'être."
    )

# En production, les statiques sont servis par WhiteNoise avec MANIFEST
# (cache-busting via noms hashés) + compression gzip/brotli. Le collectstatic
# est exécuté AU BUILD (docker/production.Dockerfile), donc le manifest existe
# déjà dans l'image. On n'active ce storage strict QU'en prod : le dev reste sur
# le storage par défaut (pas de manifest requis sans collectstatic).
STORAGES = {
    **STORAGES,  # noqa: F405 — défini dans config/settings/files_and_storages.py
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Traefik passe X-Forwarded-Host; accepter aussi le container name "django"
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["django", "localhost", "127.0.0.1"])

CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=False)

# ⚠️ `CORS_ORIGIN_WHITELIST` est un réglage MORT : django-cors-headers ne lit que
# `CORS_ALLOWED_ORIGINS`. Vérifié — avec `DJANGO_CORS_ORIGIN_WHITELIST` renseigné
# et `CORS_ALLOWED_ORIGINS` vide, la bibliothèque résout une liste VIDE et
# n'autorise donc aucune origine. Le nom est conservé pour compatibilité, mais il
# ne décide de rien : c'est le second qui compte.
#
# L'enjeu a grandi avec le passage du refresh token en cookie : le navigateur
# n'envoie un cookie cross-origin que si l'origine est explicitement autorisée
# ET `Access-Control-Allow-Credentials: true`. Une origine manquante ne produit
# aucune erreur serveur — la connexion échoue silencieusement côté navigateur.
#
# D'où le repli ci-dessous : si `CORS_ALLOWED_ORIGINS` n'est pas fourni, on
# reprend la valeur historique plutôt que de laisser une liste vide. Il ne peut
# qu'élargir vers ce qui était DÉJÀ voulu, jamais restreindre.
CORS_ORIGIN_WHITELIST = env.list(
    "DJANGO_CORS_ORIGIN_WHITELIST",
    default=env.list("CORS_ORIGIN_WHITELIST", default=[]),
)
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=CORS_ORIGIN_WHITELIST)
CORS_ALLOWED_ORIGIN_REGEXES = env.list("CORS_ALLOWED_ORIGIN_REGEXES", default=[])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# Origins autorisées au handshake WebSocket (config/asgi.py). L'Origin envoyée par
# le navigateur est le domaine du FRONT — qui n'est pas dans ALLOWED_HOSTS (domaine
# API) — donc AllowedHostsOriginValidator rejetait tous les WS en prod. À défaut de
# WS_ALLOWED_ORIGINS explicite, on réutilise CORS_ALLOWED_ORIGINS (même liste de
# fronts de confiance).
WS_ALLOWED_ORIGINS = env.list(
    "WS_ALLOWED_ORIGINS",
    default=env.list("CORS_ALLOWED_ORIGINS", default=[]),
)

SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=True)

# Le cookie porteur du refresh token (7 jours) ne doit JAMAIS transiter en clair.
# Cf. config/settings/jwt.py pour la contrainte SameSite si le front change de
# domaine enregistrable.
JWT_REFRESH_COOKIE_SECURE = env.bool("JWT_REFRESH_COOKIE_SECURE", default=True)
# Le cookie CSRF doit lui aussi être réservé à HTTPS : sans ce réglage il partait
# en clair, ce qui annule l'intérêt d'un cookie de session sécurisé.
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=True)

# Anti-clickjacking : l'API sert aussi l'admin Django et les pages d'erreur.
X_FRAME_OPTIONS = "DENY"
# Ne pas fuiter le chemin complet (qui peut contenir un identifiant de demande)
# vers un site tiers quand un utilisateur suit un lien sortant.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# HSTS — impose HTTPS côté NAVIGATEUR, en plus de SECURE_SSL_REDIRECT côté serveur.
# Différence importante : la redirection serveur se désactive instantanément, alors
# qu'un en-tête HSTS reste mémorisé par le navigateur pendant toute sa durée. Une
# valeur longue posée trop tôt rend le domaine inaccessible en HTTP pour cette durée
# si le certificat casse.
# D'où la rampe : 1 heure par défaut, sans risque. Une fois TLS confirmé stable en
# production, passer SECURE_HSTS_SECONDS à 31536000 (1 an) dans l'environnement.
# `includeSubDomains` et `preload` restent opt-in : ils engagent TOUS les
# sous-domaines, y compris ceux qui ne sont pas encore en HTTPS.
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=3600)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)

# https://docs.djangoproject.com/en/dev/ref/settings/#secure-proxy-ssl-header
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-ssl-redirect
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
# https://docs.djangoproject.com/en/dev/ref/middleware/#x-content-type-options-nosniff
SECURE_CONTENT_TYPE_NOSNIFF = env.bool("SECURE_CONTENT_TYPE_NOSNIFF", default=True)
