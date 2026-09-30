# Charge les variables du .env comme variables Make (le '-' ignore l'erreur si .env absent)
-include .env
export

.PHONY: up down restart build logs shell dbshell makemigrations migrate check test \
       init-data init-all createsuperuser import-aelf clear-cache \
	   down-v rebuild dev-deps \
       flush-redis flush-db link-verses musique-demo check-embeddings seed-embeddings seed-embeddings-force seed-embeddings-async \
       seed-prod seed-recette seed-recette-reset seed-charge \
	celery-logs celery-restart rabbitmq-stats clean-audio collectstatic reinit-bible reinit-bible-aelf import-bible-aelf \
	ci-list ci act hooks ci-docker kc-up kc-down kc-export kc-test \
	build-prod up-prod down-prod logs-prod

# ==============================================================================
# COMMANDES DOCKER
# ==============================================================================
up:
	docker compose up -d

down:
	docker compose down

down-v:
	docker compose down -v

reset: ## Full reset: supprime volumes + réinitialise (DESTRUCTIF — efface toutes les données)
	docker compose down -v
	docker compose up -d
	@echo "Attente démarrage PostgreSQL..."
	sleep 8
	$(MAKE) init-all

rebuild:
	docker compose down
	docker compose build
	docker compose up -d

restart:
	docker compose restart

build:
	docker compose build

# Installe les deps de DÉVELOPPEMENT (pytest, debug_toolbar, ...) dans les
# conteneurs en cours. À relancer après un `recreate`/`up` qui repart de l'image
# (laquelle n'embarque que requirements/base.txt). NB : après tout changement de
# code des tâches Celery, faire `make restart` pour recharger le worker.
dev-deps:
	docker compose exec django pip install -q -r requirements/local.txt
	docker compose exec celery pip install -q -r requirements/local.txt

logs:
	docker compose logs -f django


# ==============================================================================
# COMMANDES DJANGO (exécutées dans le container)
# ==============================================================================
shell:
	docker compose exec django python manage.py shell

dbshell:
	docker compose exec db psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

makemigrations:
	docker compose exec django python manage.py makemigrations

migrate:
	docker compose exec django python manage.py migrate

check:
	docker compose exec django python manage.py check

collectstatic:
	docker compose exec django python manage.py collectstatic --noinput

test:
	docker compose exec django pytest

createsuperuser:
	docker compose exec django python manage.py createsuperuser

import-aelf:
	docker compose exec django python manage.py import_aelf --start "$$(date +%Y-%m-%d)" --end "$$(python3 -c 'from datetime import datetime, timedelta; print((datetime.now() + timedelta(days=(6 - datetime.now().weekday()))).date())')"
	docker compose exec django python manage.py liturgy_link_verses

clear-cache:
	docker compose exec django python manage.py shell -c "from django.core.cache import cache; cache.clear()"

flush-redis:
	docker compose exec redis redis-cli FLUSHALL

flush-db:
	docker compose exec django python manage.py flush --no-input

# ==============================================================================
# BIBLE & RAG UTILS
# ==============================================================================
check-embeddings:
	docker compose exec django python manage.py check_embeddings

# Génère les embeddings MANQUANTS (synchrone). Prérequis : EMBEDDING_PROVIDER=local
# + PGVECTOR_ENABLED=True dans .env, puis `make restart`. 1er usage : télécharge
# le modèle local (~1 Go) dans FASTEMBED_CACHE_DIR.
# Rattache les lectures du jour aux versets de la Bible locale (après un import de la Bible).
link-verses:
	docker compose exec django python manage.py liturgy_link_verses

seed-embeddings:
	docker compose exec django python manage.py seed_embeddings

# Recalcule TOUS les embeddings (écrase d'éventuels vecteurs stub/zéro).
seed-embeddings-force:
	docker compose exec django python manage.py seed_embeddings --force

# Dispatche le calcul en arrière-plan via Celery (gros corpus / prod).
seed-embeddings-async:
	docker compose exec django python manage.py seed_embeddings --async

import-bible-aelf:
	docker compose exec django python manage.py import_bible init/bibles/format/json/bible-fr-aelf.json --source AELF
	docker compose exec django python manage.py liturgy_link_verses

reinit-bible:
	docker compose exec django python manage.py shell -c "from apps.bible.models import Verse, Chapter, Book, DailyText; Verse.objects.all().delete(); Chapter.objects.all().delete(); Book.objects.all().delete(); DailyText.objects.all().delete(); print('Bible data cleared.')"
	docker compose exec django python manage.py import_bible init/bibles/format/json/bible-fr-aelf.json --source bible_fr
	docker compose exec django python manage.py import_aelf --start "$$(date +%Y-%m-%d)" --end "$$(python3 -c 'from datetime import datetime, timedelta; print((datetime.now() + timedelta(days=(6 - datetime.now().weekday()))).date())')"
	docker compose exec django python manage.py liturgy_link_verses
	docker compose exec django python manage.py shell -c "from django.core.cache import cache; cache.clear(); print('Cache cleared.')"

reinit-bible-aelf:
	docker compose exec django python manage.py shell -c "from apps.bible.models import Verse, Chapter, Book, DailyText; Verse.objects.all().delete(); Chapter.objects.all().delete(); Book.objects.all().delete(); DailyText.objects.all().delete(); print('Bible data cleared.')"
	docker compose exec django python manage.py import_bible init/bibles/format/json/bible-fr-aelf.json --source AELF
	docker compose exec django python manage.py import_aelf --start "$$(date +%Y-%m-%d)" --end "$$(python3 -c 'from datetime import datetime, timedelta; print((datetime.now() + timedelta(days=(6 - datetime.now().weekday()))).date())')"
	docker compose exec django python manage.py liturgy_link_verses
	docker compose exec django python manage.py shell -c "from django.core.cache import cache; cache.clear(); print('Cache cleared.')"

# ==============================================================================
# INFRASTRUCTURE & MAINTENANCE
# ==============================================================================
celery-logs:
	docker compose logs -f celery

celery-restart:
	docker compose restart celery

rabbitmq-stats:
	docker compose exec rabbitmq rabbitmqctl list_queues

clean-audio:
	docker compose exec django python manage.py shell -c "import os; from django.conf import settings; path = os.path.join(settings.MEDIA_ROOT, 'rosary'); [os.remove(os.path.join(path, f)) for f in os.listdir(path) if f.endswith('.mp3')]; print('Local audio cache cleaned.')"

# ==============================================================================
# INITIALISATION DU PROJET (cross-platform, ne requiert pas bash sur l'hôte)
# ==============================================================================
init-data:
	@echo "1. Migrations Django..."
	docker compose exec django python manage.py migrate
	@echo "2. Script conditionnel pgvector..."
	docker compose exec -T db psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) < init/postgresql/pgvector_conditional.sql
	@echo "3. Buckets MinIO (audio du Rosaire public, fichiers prives)..."
	docker compose exec minio sh -c "mc alias set local $(AWS_S3_ENDPOINT_URL) $(MINIO_ROOT_USER) $(MINIO_ROOT_PASSWORD) && mc mb local/rosary-audio || true && mc anonymous set public local/rosary-audio && mc mb --ignore-existing local/$(AWS_STORAGE_BUCKET_NAME)"

# ==============================================================================
# SEEDS — deux commandes seulement
# ==============================================================================
# seed-prod    : données RÉELLES (référentiel territorial, Bible, Rosaire, liturgie AELF
#                rattachée aux versets). Production et recette. Idempotent.
# seed-recette : seed-prod + personnes de démonstration + données de test réalistes +
#                musique de démo (seed_assets/musique-demo/ ou dossier seed-assets/ du bucket de l'app).
#                JAMAIS en production. Défaut local : échelle petite (serveur : moyenne).
# Options : make seed-recette SEED_ARGS="--echelle moyenne --sans-musique --hors-ligne"
# Sur le serveur : python manage.py seed_prod / SEED_ALLOWED=true python manage.py seed_recette
SEED_ARGS ?= --echelle petite

seed-prod:
	docker compose exec django python manage.py seed_prod

seed-recette:
	docker compose exec -e SEED_ALLOWED=true django python manage.py seed_recette $(SEED_ARGS)

# Retire les données de test et de démonstration (les données réelles restent). MANUEL.
seed-recette-reset:
	docker compose exec -e SEED_ALLOWED=true django python manage.py seed_recette --reset

# Musique de démo (une fois) : pack décompressé dans seed_assets/, jamais commité.
# En recette : ajouter --publier pour la garder sous seed-assets/ dans le bucket de l'app.
musique-demo:
	docker compose exec django python manage.py prepare_musique_demo $(MUSIQUE_ARGS)

# Tests de charge : échelle grande (COPY en masse), sans fichiers audio.
seed-charge:
	docker compose exec -e SEED_ALLOWED=true django python manage.py seed_realiste --profil local --echelle grande --medias aucun --verifier

# Base neuve : migrations, pgvector, buckets, puis les données réelles.
init-all: init-data seed-prod


# ==============================================================================
# KEYCLOAK (ADR-004) — realm versionné dans infra/keycloak/realm-jangubi.json
# ==============================================================================
# Démarre Keycloak (http://localhost:8180, admin/admin en local) et importe le realm.
kc-up:
	@grep -Eq '^KEYCLOAK_ADMIN_CLIENT_SECRET=.{16,}' .env || { echo "✗ KEYCLOAK_ADMIN_CLIENT_SECRET absent ou trop court dans .env (openssl rand -hex 32)."; exit 1; }
	docker compose --profile keycloak up -d keycloak

kc-down:
	docker compose --profile keycloak stop keycloak keycloak-db

# Exporte le realm courant (après un réglage fait dans la console) pour le versionner.
# Relire le diff : l'export contient des secrets de clients à remplacer par ${...}.
kc-export:
	docker compose --profile keycloak exec keycloak /opt/keycloak/bin/kc.sh export --realm jangubi --file /tmp/realm-jangubi.json --users skip
	docker compose --profile keycloak cp keycloak:/tmp/realm-jangubi.json infra/keycloak/realm-jangubi.export.json

# Test d'intégration contre le Keycloak local (hors CI).
kc-test:
	docker compose exec -e KEYCLOAK_E2E_URL=http://keycloak:8080 django pytest -m keycloak apps/authentication -q

# ==============================================================================
# CI LOCALE (act) — reproduit .github/workflows/django.yml en local
# ==============================================================================
# Image runner act (catthehacker ≈ runner ubuntu de GitHub).
ACT_RUNNER := ubuntu-24.04=catthehacker/ubuntu:act-24.04

# Liste les jobs du workflow sans rien exécuter (valide le parsing YAML).
ci-list:
	act --list

# Lance le job `build` en local (install + ruff + mypy + pytest), comme la CI.
ci:
	act push -P $(ACT_RUNNER) --rm --job build

# Alias pratique.
act: ci

# Installe le hook pre-push (make act avant tout push vers develop/stage/main).
hooks:
	git config core.hooksPath scripts/git-hooks
	@echo "Hook pre-push installé (scripts/git-hooks/pre-push)."

# Valide EN LOCAL le build de l'image de production (ce que construit
# livraison-recette.yml). NE POUSSE PAS — pour débugger le Dockerfile avant un tag/push.
ci-docker:
	docker build -f docker/production.Dockerfile -t jangubi-backend:local .

# ==============================================================================
# RUN LOCAL DE L'IMAGE DE PRODUCTION (compose override)
# ==============================================================================
# Lance django/celery/beats avec la cible `production` (non-root appuser, venv
# sans outils de dev, AUCUN bind-mount du code) + l'infra du compose de base.
# Reproduit la prod en local. À ne pas lancer en même temps que `make up` (mêmes
# container_names / volumes).
PROD_COMPOSE := -f docker-compose.yml -f docker-compose.prod.yml

build-prod:
	docker compose $(PROD_COMPOSE) build

up-prod:
	docker compose $(PROD_COMPOSE) up -d --build

down-prod:
	docker compose $(PROD_COMPOSE) down

logs-prod:
	docker compose $(PROD_COMPOSE) logs -f django
