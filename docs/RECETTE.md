# Environnement de recette (staging)

La recette fait tourner **l'image de production** avec les réglages `config.django.staging`, sur une
pile complète et autonome (`docker-compose.staging.yml`). Elle sert à valider les écrans web et
mobile contre le vrai backend avant la production. Elle ne contient **aucune donnée réelle** :
seulement le référentiel territorial et les personnes de démonstration.

## Ce qui diffère de la production

`config/django/staging.py` hérite de `config/django/production.py` (DEBUG coupé, `SECRET_KEY` et
`MESSAGING_ENCRYPTION_KEY` obligatoires et distinctes, statiques WhiteNoise, admin Django fermée),
avec trois écarts :

| Réglage | Recette | Production |
|---|---|---|
| Dons | agrégateur **factice** admis (`DONATIONS_PROVIDER=fake`), aucun paiement réel | module retiré si l'agrégateur est factice |
| HTTPS | non imposé par défaut (`SECURE_SSL_REDIRECT`, cookies sécurisés, HSTS pilotés par l'environnement) | imposé |
| Sentry | `SENTRY_ENVIRONMENT=staging` | `production` |

## Services

| Service | Rôle | Accès hôte |
|---|---|---|
| `django` | API HTTP, WebSocket et SSE (daphne, ASGI) ; applique les migrations au démarrage | http://localhost:8100 |
| `celery` | files `default` (e-mails, notifications, push, webhooks) et `reco` (recommandations) | — |
| `celery-media` | file `media` : encodage audio (image avec **ffmpeg**, concurrence 1) | — |
| `beat` | planificateur (planning en base, django-celery-beat) | — |
| `db` | Postgres 17 + pgvector + pg_stat_statements | non publié |
| `redis` | cache, présence, relais SSE, couche Channels | non publié |
| `rabbitmq` | courtier Celery | console http://127.0.0.1:15673 |
| `minio` + `minio-init` | stockage objet ; `minio-init` crée le bucket privé des médias puis s'arrête | API http://localhost:9100, console http://localhost:9101 |
| `keycloak` + `keycloak-db` | authentification (ADR-004), realm `jangubi` importé au premier démarrage | http://localhost:8280 |
| `mailpit` | capture tous les e-mails (Django et Keycloak) | http://localhost:8026 |

Les ports sont décalés par rapport à la pile de dev (`docker-compose.yml`) : les deux peuvent
tourner sur le même poste.

Le worker `celery-media` utilise la même image que l'API : `docker/production.Dockerfile` installe
ffmpeg pour l'encodage de la sonothèque.

## Démarrage

```bash
cp .env.staging.example .env.staging
# Remplacer chaque CHANGE_ME. Secrets : python -c "import secrets; print(secrets.token_hex(32))"
# DATABASE_URL, CELERY_BROKER_URL et AWS_S3_SECRET_ACCESS_KEY reprennent POSTGRES_PASSWORD,
# RABBITMQ_PASSWORD et MINIO_ROOT_PASSWORD.

docker compose -f docker-compose.staging.yml --env-file .env.staging up -d --build
docker compose -f docker-compose.staging.yml --env-file .env.staging ps
```

`--env-file .env.staging` est nécessaire : il alimente à la fois les conteneurs et les valeurs du
fichier compose (mots de passe Postgres, RabbitMQ, MinIO, Keycloak). Une variable obligatoire
absente arrête `docker compose` avec un message explicite.

Pour ne pas répéter les options :

```bash
export COMPOSE_FILE=docker-compose.staging.yml COMPOSE_ENV_FILES=.env.staging
docker compose logs -f django celery-media
```

### Données de démonstration

Une fois `django` en bonne santé (migrations passées) :

```bash
# Référentiel territorial (province, diocèses, doyennés de Dakar, paroisse pilote Saint-Dominique)
docker compose exec django python manage.py seed_hierarchy_profile senegal
# Personnes, nominations, contenus et dons de démonstration (idempotent ; --reset pour tout retirer)
docker compose exec django python manage.py seed_demo
# Comptes Keycloak correspondants (même adresse e-mail, mot de passe KC_DEMO_PASSWORD)
set -a; . ./.env.staging; set +a
bash infra/keycloak/seed-demo-users.sh
```

### Données de test réalistes

Pour une recette peuplée (12 paroisses, 5 000 fidèles, dons sur douze mois, sonothèque encodée par le vrai
pipeline, écoutes et recommandations) : `make seed-recette` (détails : `docs/DONNEES-DE-TEST.md`). Les médias
libres sont rangés une fois dans le bucket MinIO `seed-assets` (`fetch_seed_assets --profil recette`) ; les
comptes Keycloak des personas sont créés avec le mot de passe commun de recette `KC_DEMO_PASSWORD`
(`.env.staging`). Remise à zéro **manuelle uniquement** : `make seed-recette-reset`. Trafic simulé pour voir
bouger le SSE : `make seed-recette-trafic`.

Optionnel : Bible, Rosaire et liturgie du jour (`import_bible`, `seed_rosary`, `import_aelf`),
mêmes commandes que la cible `init-data` du `Makefile`, avec `docker compose exec django …`.

## Comptes

| Compte | Accès |
|---|---|
| Console Keycloak | http://localhost:8280/admin — `KEYCLOAK_ADMIN_USER` / `KEYCLOAK_ADMIN_PASSWORD` |
| Console MinIO | http://localhost:9101 — `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` |
| Console RabbitMQ | http://127.0.0.1:15673 — `RABBITMQ_USER` / `RABBITMQ_PASSWORD` |
| Personnes de démonstration | `<clé>@demo.jangubi.sn`, mot de passe `KC_DEMO_PASSWORD` |

Clés des personnes de démonstration (`seed_demo`) :

| Clé | Personne | Rôle |
|---|---|---|
| `fidele`, `fidele2` | Awa Diop, Moussa Mendy | fidèles de la paroisse pilote |
| `mineur` | Fatou Sène | fidèle mineure (messagerie refusée, avec explication) |
| `cure` | P. Joseph Sarr | curé de la paroisse pilote |
| `vicaire` | P. Paul Diouf | vicaire paroissial |
| `secretaire` | Marie Faye | secrétaire paroissiale |
| `econome` | Anne Mendy | économe paroissiale (dons) |
| `doyen` | P. Augustin Ndiaye | doyen |
| `chancelier` | P. Théodore Diatta | chancelier (diocèse) |
| `econome_dio` | Bernard Coly | économe diocésain |
| `admin_paroissial` | P. Robert Sagna | administrateur d'une seconde paroisse |
| `plateforme` | Mariama Ba | administratrice plateforme (rôle `platform_admin`) |

Les responsables doivent enrôler un TOTP à la première connexion (`KEYCLOAK_REQUIRE_MFA_FOR_STAFF`).

## URLs utiles

- API : http://localhost:8100/api/v1/
- Schéma OpenAPI : http://localhost:8100/api/schema/ — Swagger : http://localhost:8100/api/swagger-ui/
- Émetteur OIDC : http://localhost:8280/realms/jangubi
- E-mails capturés : http://localhost:8026

## Brancher les fronts

- **Web** (Next, `.env.local`) : `NEXT_PUBLIC_API_URL=http://localhost:8100/api` (sans `/v1`),
  `NEXT_PUBLIC_KEYCLOAK_URL=http://localhost:8280`, `NEXT_PUBLIC_KEYCLOAK_REALM=jangubi`,
  `NEXT_PUBLIC_KEYCLOAK_CLIENT_ID=jangubi-web`, mocks désactivés (`NEXT_PUBLIC_API_MOCKING` vide).
  Le rappel doit correspondre exactement à `KC_WEB_REDIRECT_URI`, et l'origine du front à
  `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` et `KC_WEB_ORIGIN`.
- **Mobile** (`template/.env`) : `USE_MOCKS=false`, `API_URL=http://<ip-du-poste>:8100/api`,
  `WS_URL=ws://<ip-du-poste>:8100`, `KEYCLOAK_URL=http://<ip-du-poste>:8280`,
  `KEYCLOAK_CLIENT_ID=jangubi-mobile`. L'émetteur des jetons doit être le même que
  `KEYCLOAK_SERVER_URL` de l'API : sur appareil, mettre l'adresse IP du poste (ou le domaine de
  recette) dans les deux, jamais `localhost` d'un côté et une IP de l'autre.

Si la recette est exposée sous un domaine : remplacer `localhost` dans `KEYCLOAK_SERVER_URL`,
`MINIO_PUBLIC_URL`, `ALLOWED_HOSTS`, les origines et les rappels OIDC ; derrière un proxy TLS,
passer `NUM_PROXIES=1` et les réglages HTTPS de `.env.staging.example`. Le realm n'est importé
qu'au **premier** démarrage de Keycloak : changer ensuite un rappel dans la console, ou repartir
d'un volume `keycloak_db_data` vide.

## Vérifications rapides

```bash
docker compose config -q                                     # syntaxe et variables obligatoires
docker compose exec django python manage.py check --deploy   # avertissements HTTPS attendus en HTTP
docker compose exec celery-media ffmpeg -version
```

## Arrêt et remise à zéro

```bash
docker compose down        # garde les volumes
docker compose down -v     # efface base, fichiers, comptes Keycloak : recette à reconstruire
```
