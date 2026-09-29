"""Environnement de RECETTE (staging) : docs/RECETTE.md (déployé par le dépôt Infrastructure).

Mêmes garde-fous que la production (DEBUG coupé, SECRET_KEY et MESSAGING_ENCRYPTION_KEY
obligatoires et distinctes, statiques WhiteNoise, admin Django fermée par défaut), avec trois
écarts assumés pour une recette :

- l'agrégateur de paiement **factice** est admis (``DONATIONS_PROVIDER=fake``) : on recette les
  dons de bout en bout sans aucun paiement réel (la production retire alors le module) ;
- HTTPS n'est pas imposé par défaut (``SECURE_SSL_REDIRECT``, cookies sécurisés et HSTS pilotés
  par l'environnement) : la recette peut tourner en HTTP sur un poste ou derrière un proxy TLS ;
- ``SENTRY_ENVIRONMENT`` vaut ``staging`` par défaut.

Aucune donnée réelle en recette : comptes et paroisse de démonstration (``seed_demo``).
"""

import os

from apps.core.modules import filter_beat_schedule
from config.env import env

os.environ.setdefault("SENTRY_ENVIRONMENT", "staging")

from .production import *  # noqa: E402, F403
from .production import _CELERY_BEAT_SCHEDULE_ALL  # noqa: E402

JANGUBI_ENVIRONMENT = "staging"

# La production retire « donations » quand l'agrégateur est factice : la recette le garde.
JANGUBI_MODULES = env.list("JANGUBI_MODULES", default=list(V1_DEFAULT_MODULES))  # noqa: F405
CELERY_BEAT_SCHEDULE = filter_beat_schedule(_CELERY_BEAT_SCHEDULE_ALL, active=JANGUBI_MODULES)

# HTTP admis en recette locale ; derrière un proxy TLS, passer ces réglages à True.
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=False)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=False)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
