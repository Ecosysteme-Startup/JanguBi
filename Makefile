# Charge les variables du .env comme variables Make (le '-' ignore l'erreur si .env absent)
-include .env
export

.PHONY: up down restart build logs shell dbshell makemigrations migrate check test \
       init-data create-admin init-all createsuperuser import-aelf clear-cache \
	   down-v rebuild dev-deps \
       flush-redis flush-db check-embeddings seed-embeddings seed-embeddings-force seed-embeddings-async \
       seed seed-senegal seed-demo seed-reset \
	celery-logs celery-restart rabbitmq-stats clean-audio collectstatic reinit-bible reinit-bible-aelf import-bible-aelf init-tv-categories \
	ci-list ci act hooks ci-docker ci-docker-act \
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

clear-cache:
	docker compose exec django python manage.py shell -c "from django.core.cache import cache; cache.clear()"

flush-redis:
	docker compose exec redis redis-cli FLUSHALL

flush-db:
	docker compose exec django python manage.py flush --no-input

init-tv-categories:
	docker compose exec django python manage.py init_tv_categories

# ==============================================================================
# BIBLE & RAG UTILS
# ==============================================================================
check-embeddings:
	docker compose exec django python manage.py check_embeddings

# Génère les embeddings MANQUANTS (synchrone). Prérequis : EMBEDDING_PROVIDER=local
# + PGVECTOR_ENABLED=True dans .env, puis `make restart`. 1er usage : télécharge
# le modèle local (~1 Go) dans FASTEMBED_CACHE_DIR.
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

reinit-bible:
	docker compose exec django python manage.py shell -c "from apps.bible.models import Verse, Chapter, Book, DailyText; Verse.objects.all().delete(); Chapter.objects.all().delete(); Book.objects.all().delete(); DailyText.objects.all().delete(); print('Bible data cleared.')"
	docker compose exec django python manage.py import_bible init/bibles/format/json/bible-fr-aelf.json --source bible_fr
	docker compose exec django python manage.py import_aelf --start "$$(date +%Y-%m-%d)" --end "$$(python3 -c 'from datetime import datetime, timedelta; print((datetime.now() + timedelta(days=(6 - datetime.now().weekday()))).date())')"
	docker compose exec django python manage.py shell -c "from django.core.cache import cache; cache.clear(); print('Cache cleared.')"

reinit-bible-aelf:
	docker compose exec django python manage.py shell -c "from apps.bible.models import Verse, Chapter, Book, DailyText; Verse.objects.all().delete(); Chapter.objects.all().delete(); Book.objects.all().delete(); DailyText.objects.all().delete(); print('Bible data cleared.')"
	docker compose exec django python manage.py import_bible init/bibles/format/json/bible-fr-aelf.json --source AELF
	docker compose exec django python manage.py import_aelf --start "$$(date +%Y-%m-%d)" --end "$$(python3 -c 'from datetime import datetime, timedelta; print((datetime.now() + timedelta(days=(6 - datetime.now().weekday()))).date())')"
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
	@echo "==========================================================="
	@echo "   Initialisation de la base de donnees Bible"
	@echo "==========================================================="
	@echo "1. Application des migrations Django..."
	docker compose exec django python manage.py migrate
	@echo "2. Importation du format A (bible-fr.json)..."
	docker compose exec django python manage.py import_bible init/bibles/format/json/bible-fr-aelf.json --source bible_fr
	@echo "3. Execution du script conditionnel pgvector..."
	docker compose exec -T db psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) < init/postgresql/pgvector_conditional.sql
	@echo "4. Creation et configuration du bucket MinIO..."
	docker compose exec minio sh -c "mc alias set local $(AWS_S3_ENDPOINT_URL) $(MINIO_ROOT_USER) $(MINIO_ROOT_PASSWORD) && mc mb local/rosary-audio || true && mc anonymous set public local/rosary-audio"
	@echo "5. Importation des donnees du Rosaire..."
	docker compose exec django python manage.py seed_rosary
	@echo "6. Importation de la liturgie du jour (AELF)..."
	docker compose exec django python manage.py import_aelf --start "$$(date +%Y-%m-%d)" --end "$$(python3 -c 'from datetime import datetime, timedelta; print((datetime.now() + timedelta(days=(6 - datetime.now().weekday()))).date())')"
	@echo "==========================================================="
	@echo "   Importation et Indexation terminees !"
	@echo "==========================================================="

create-admin:
	@echo "==========================================================="
	@echo "   Creation du Super Administrateur"
	@echo "==========================================================="
	docker compose exec django python manage.py init_admin

# ── Seed (structure territoriale + donnees de demo) ──────────────────────────
seed-senegal:
	docker compose exec django python manage.py seed_senegal

seed-demo:
	docker compose exec django python manage.py seed_demo

seed-reset:
	docker compose exec django python manage.py seed_demo --reset

# Une seule commande : seed_senegal (prerequis) PUIS seed_demo. Idempotent.
seed: seed-senegal seed-demo
	@echo "==========================================================="
	@echo "   Seed termine (seed_senegal + seed_demo) — multi-appartenance"
	@echo "==========================================================="

# `seed-senegal` fait partie de l'initialisation, pas des données de démo : sans
# structure territoriale, AUCUN compte ne peut finir son onboarding. La sélection
# de paroisse est obligatoire et bloquante — menu vide, bouton grisé, aucun moyen
# de passer l'étape (audit beta 2026-07-20). `seed_senegal` est idempotent.
init-all: init-data seed-senegal


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

# Valide EN LOCAL le build de l'image de production (ce que construit le job
# build-docker). NE POUSSE PAS — pour débugger le Dockerfile avant un tag/push.
ci-docker:
	docker build -f docker/production.Dockerfile -t jangubi-backend:local .

# Lance le job build-docker via act (build + push DockerHub). Nécessite un fichier
# `.secrets` avec DOCKERHUB_USERNAME / DOCKERHUB_TOKEN. ⚠️ pousse réellement l'image.
ci-docker-act:
	act push -P $(ACT_RUNNER) --rm --job build-docker --secret-file .secrets

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
