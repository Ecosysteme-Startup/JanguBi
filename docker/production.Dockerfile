# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# Image de PRODUCTION pour JanguBi (backend Django) — build multi-stage.
#
#   docker build -f docker/production.Dockerfile -t jangubi-backend:prod .
#
# Principe du multi-stage : on COMPILE les dépendances dans un étage jetable
# (gcc, headers, uv… ~300 Mo d'outils), puis on COPIE seulement le résultat
# (le venv) dans une image finale légère. Les outils de build ne se retrouvent
# JAMAIS dans l'image déployée → plus petite + plus sûre. Le dernier stage
# (`production`) est l'image produite par défaut.
# ─────────────────────────────────────────────────────────────────────────────


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 1 — base : socle runtime minimal (partagé avec docker/local.Dockerfile)
# ═══════════════════════════════════════════════════════════════════════════
# "slim" = Debian allégée, SANS outils de compilation (ajoutés dans le builder).
FROM python:3.12.4-slim AS base

# Variables valables dans tous les étages héritant de `base`.
#   PYTHONUNBUFFERED=1        → logs Python immédiats (pas de buffer)
#   PYTHONDONTWRITEBYTECODE=1 → pas de .pyc inutiles dans l'image
#   PIP_NO_CACHE_DIR=1        → pip ne garde pas son cache
#   VIRTUAL_ENV + PATH        → "active" le venv : tout python/pip pointe vers /opt/venv
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Librairies SYSTÈME nécessaires à l'EXÉCUTION (pas au build) :
#   libpq5   → client PostgreSQL requis par psycopg2 au runtime
#   ffmpeg   → encodage et normalisation des pistes de la sonothèque (apps/audio)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 2 — builder : compile + installe les dépendances de PROD dans un venv
# ═══════════════════════════════════════════════════════════════════════════
FROM base AS builder

# Outils de BUILD (lourds) — restent dans ce stage, pas dans l'image finale :
#   build-essential → gcc, make… (pour compiler psycopg2 qui n'a pas de wheel)
#   libpq-dev       → en-têtes PostgreSQL (pour compiler psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# uv : installeur ultra-rapide (créateurs de ruff). Installé sur le python SYSTÈME
# *avant* de créer le venv → il atterrit dans /usr/local (pas dans /opt/venv),
# donc il n'est PAS copié dans l'image finale. Il sert juste à remplir le venv.
RUN pip install --no-cache-dir uv

# venv isolé qu'on copiera tel quel dans l'image finale.
RUN python -m venv "$VIRTUAL_ENV"

# On copie d'ABORD les requirements : tant qu'ils ne changent pas, Docker réutilise
# le cache de la couche d'install (gros gain de temps).
COPY requirements/ requirements/

# Dépendances de PRODUCTION uniquement (base.txt). uv installe dans le venv actif.
RUN uv pip install -r requirements/base.txt


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 3 — production : IMAGE FINALE légère (aucun outil de build, non-root)
# ═══════════════════════════════════════════════════════════════════════════
FROM base AS production

# Utilisateur non-root (sécurité). --uid 1000 = uid hôte habituel (volumes).
RUN useradd --create-home --uid 1000 appuser

# Cœur du multi-stage : on récupère le venv déjà construit, sans gcc ni headers.
COPY --from=builder $VIRTUAL_ENV $VIRTUAL_ENV

WORKDIR /app
# Code applicatif (respecte .dockerignore : pas de .venv/.git/.env…).
# --chown pose la propriété EN MÊME TEMPS que la copie → une seule couche.
COPY --chown=appuser:appuser . /app

# Fichiers statiques collectés AU BUILD → bakés dans l'image (immuable).
# Pourquoi ici et pas au runtime : /app est possédé par root (créé par WORKDIR),
# donc l'appuser non-root ne peut PAS y créer /app/staticfiles → PermissionError
# sur collectstatic au runtime. En le faisant au build (en tant que root), le
# dossier est créé et peuplé une fois pour toutes. WhiteNoise utilise le
# CompressedManifestStaticFilesStorage : sans cette collecte, l'app renvoie 500.
# production.py exige SECRET_KEY *et* MESSAGING_ENCRYPTION_KEY à l'import →
# valeurs JETABLES, utilisées uniquement le temps de cette commande (le vrai
# .env les surcharge au runtime). Elles doivent être DIFFÉRENTES l'une de
# l'autre : le garde-fou refuse une clé de chiffrement égale à SECRET_KEY, pour
# qu'une rotation de secret ne rende jamais l'historique pastoral illisible.
# Aucune de ces valeurs ne chiffre quoi que ce soit — collectstatic ne touche
# pas la base. On rend ensuite staticfiles à appuser pour qu'un `collectstatic`
# manuel reste possible.
RUN SECRET_KEY="collectstatic-build-only" \
    MESSAGING_ENCRYPTION_KEY="collectstatic-build-only-messaging" \
    DJANGO_SETTINGS_MODULE=config.django.production \
    python manage.py collectstatic --noinput \
 && chown -R appuser:appuser /app/staticfiles

USER appuser

# Scripts de démarrage (dans /app/docker, exécutables dans Git) : une SEULE image
# pour l'API, le worker et le beat — l'Infrastructure choisit l'entrypoint :
#   api    → /app/docker/entrypoint.sh (migre si besoin) + CMD ci-dessous
#   worker → /app/docker/celery_entrypoint.sh
#   beat   → /app/docker/beats_entrypoint.sh
# Migration explicite (make deployer, conteneur éphémère) :
#   python manage.py migrate --noinput
EXPOSE 8000

# Sonde de l'API : port ouvert, en Python (pas de curl dans l'image slim). Le
# worker et le beat doivent la SURCHARGER dans Compose (ils n'écoutent rien).
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=5 \
  CMD ["python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8000), 3).close()"]

# En prod on sert l'app ASGI avec Daphne (WebSocket/Channels et flux SSE).
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "--proxy-headers", "config.asgi:application"]
