# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# Image LOCALE / DÉVELOPPEMENT pour JanguBi (backend Django) — build multi-stage.
#
#   docker build -f docker/local.Dockerfile -t jangubi-backend:dev .
#   (utilisée par docker-compose.yml ; le code est bind-monté par-dessus /app)
#
# Mêmes stages base + builder que docker/production.Dockerfile, plus un stage
# `builder-dev` qui ajoute les outils de dev (pytest, mypy, ruff, ipython…), et
# un stage final `development` qui tourne en root pour le confort (bind-mount,
# pip à la volée) avec le serveur de dev Django.
# ─────────────────────────────────────────────────────────────────────────────


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 1 — base : socle runtime minimal (identique à production.Dockerfile)
# ═══════════════════════════════════════════════════════════════════════════
FROM python:3.12.4-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Librairies SYSTÈME runtime : libpq5 (psycopg2), libgomp1 (onnxruntime/fastembed), ffmpeg (apps/audio).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libgomp1 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 2 — builder : dépendances de PROD dans un venv (identique à production)
# ═══════════════════════════════════════════════════════════════════════════
FROM base AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# uv sur le python SYSTÈME (avant le venv) → pas embarqué dans le venv copié.
RUN pip install --no-cache-dir uv

RUN python -m venv "$VIRTUAL_ENV"

COPY requirements/ requirements/

RUN uv pip install -r requirements/base.txt


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 3 — builder-dev : AJOUTE les dépendances de DÉVELOPPEMENT au venv
# ═══════════════════════════════════════════════════════════════════════════
# Hérite du builder (base.txt déjà installé + en cache) et ajoute local.txt
# (pytest, mypy, ruff, ipython, debug-toolbar, stubs…). local.txt fait -r base.txt
# mais comme c'est déjà installé, uv n'installe que le supplément.
FROM builder AS builder-dev
RUN uv pip install -r requirements/local.txt


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 4 — development : IMAGE DE DEV (venv avec outils + root pour le confort)
# ═══════════════════════════════════════════════════════════════════════════
FROM base AS development

# On récupère le venv COMPLET (base + outils dev) depuis builder-dev.
COPY --from=builder-dev $VIRTUAL_ENV $VIRTUAL_ENV

COPY entrypoint.sh /docker-entrypoint.sh
RUN sed -i 's/\r$//' /docker-entrypoint.sh && chmod +x /docker-entrypoint.sh

WORKDIR /app
# En dev, docker-compose bind-monte le code sur /app (ce COPY n'est qu'un repli
# si on lance l'image sans volume). On reste ROOT en dev : pas de soucis de
# permissions avec le volume monté, et on peut pip-install à la volée.
COPY . /app

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
