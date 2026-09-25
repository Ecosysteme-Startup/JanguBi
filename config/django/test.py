import os

# This is extremely "eye-poking",
# but we need it, if we want to ignore the debug toolbar in tests
# This is needed because of the way we setup Django Debug Toolbar.
# Since we import base settings, the entire setup will be done, before we have any chance to change it.
# A different way of approaching this would be to have a separate set of env variables for tests.
os.environ.setdefault("DEBUG_TOOLBAR_ENABLED", "False")

from .base import *  # noqa

# Based on https://www.hacksoft.io/blog/optimize-django-build-to-run-faster-on-github-actions

DEBUG = False

# La suite de tests exerce TOUS les modules, y compris gelés (ADR-006 : le code
# gelé reste maintenu). Le gel lui-même est testé dans apps/core/tests/test_modules.py.
from apps.core.modules import FREEZABLE_MODULES  # noqa: E402

JANGUBI_MODULES = list(FREEZABLE_MODULES)
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CELERY_BROKER_BACKEND = "memory"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Recherche sémantique : on n'embarque JAMAIS un modèle ML en CI/tests.
# Embeddings = stub (vecteurs zéro déterministes) ; chemin pgvector activé pour
# exercer le code vectoriel sans téléchargement de modèle.
EMBEDDING_PROVIDER = "stub"
PGVECTOR_ENABLED = True
RAG_GENERATION_ENABLED = False

# Throttling désactivé par défaut dans la suite (évite des 429 parasites entre
# tests via le cache locmem partagé). Les tests de throttling ré-activent un
# rate explicite via @override_settings.
#
# ⚠️ Ce dictionnaire REMPLACE celui de `base.py`, il ne le complète pas : toute
# portée déclarée là-bas doit être reprise ici, sinon la classe de throttle
# correspondante lève `ImproperlyConfigured: No default throttle rate set` et
# fait tomber tous les tests qui touchent l'endpoint. C'est arrivé en ajoutant
# la portée `login` — invisible en local (réglages `base`), rouge en CI.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_RATES": {
        "anon": None,
        "user": None,
        "rag": None,
        "login": None,
    },
}

# Mot de passe plus rapide à hasher en test
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]


# Email → en mémoire, pas de vrai serveur
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
