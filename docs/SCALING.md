# Montée en charge : seuils, mesures et index

Ce document est la version exploitable des §2 et §3 du plan V2 (lot B2). La règle ne change pas :
**on mesure, on corrige le goulot, puis on recommence.** On n'ajoute rien qu'une mesure ne justifie.

## 1. Hypothèse de charge

À vérifier dès la mise en production :
- dans 12 mois, 20 000 à 50 000 comptes ;
- 2 000 à 5 000 utilisateurs actifs en même temps au pic du dimanche matin ;
- quelques milliers de pistes audio.

La charge se compose de beaucoup de lectures : lectures du jour, audio, catalogue, synthèses. Les
écritures sont rares, sauf les événements d'écoute. Les pics sont courts, autour des messes.

## 2. Seuils de déclenchement

Chaque seuil se lit **au pic du dimanche**, sur 3 dimanches de suite, et **après** cache et index.
Un pic isolé ne déclenche rien.

| Signal (Prometheus / Postgres) | Seuil | Action |
|---|---|---|
| CPU du conteneur Daphne | > 60 % | Deuxième instance Daphne derrière Traefik. L'app est sans état : sessions et tickets dans Redis, fichiers sur S3. |
| p95 des temps de réponse de l'API (`django_http_requests_latency_seconds_by_view_method`) | > 500 ms sur une vue de lecture | Cache Redis sur cette vue (TTL : 60 s pour les synthèses, 10 min pour le catalogue, jusqu'à minuit pour les lectures du jour), puis index (§4). |
| Connexions Postgres actives (`pg_stat_activity`) | > 60 % de `max_connections`, ou une 2ᵉ instance Daphne ou un 3ᵉ worker Celery ajouté | **PgBouncer** en mode transaction (§3). |
| CPU de Postgres | > 70 %, après cache et index | **Réplique en lecture**. Les écritures et la lecture de ses propres écritures restent sur la base principale. |
| Taux de cache de Postgres (`blks_hit / (blks_hit + blks_read)`) | < 99 % | Plus de RAM : `shared_buffers` à 25 % de la RAM, `effective_cache_size` à 70 %. |
| Table des événements d'écoute | dès sa création (lot B3) | **Partitionnement** mensuel (§5). |
| File Celery `media` | > 20 messages pendant 10 min | Deuxième worker `media`, concurrence 2 au plus par machine (ffmpeg est limité par le CPU). |
| File `default` | > 100 messages pendant 5 min | Chercher une tâche lente d'abord (Flower). Si rien : concurrence 2 pour le worker `default`. |
| Taux d'erreurs 5xx | > 1 % pendant 5 min | Alerte. On regarde Sentry avant de toucher à l'infrastructure. |

**On n'ajoute pas** : Kafka, Kubernetes, microservices, Elasticsearch, sharding, une base de
recommandation dédiée. Rien de ce qui a été mesuré ne le justifie.

## 3. Connexions et PgBouncer

État actuel :
- Daphne ouvre une connexion par requête synchrone (`CONN_MAX_AGE=0`).
- Les WebSocket passent par `database_sync_to_async`, qui ferme la connexion après chaque appel.
- Un **flux SSE ne garde ni transaction ni connexion** : la vue est hors `ATOMIC_REQUESTS` et rend
  sa connexion avant de diffuser.
- Les workers Celery gardent une connexion par processus.

Quand un seuil du §2 le demande, on ajoute PgBouncer en **mode transaction**.

Avant la bascule, dans les réglages Django :
- `DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True` : `.iterator()` utilise des curseurs
  serveur, que le mode transaction casse ;
- `CONN_MAX_AGE` à 0, ou la valeur de `server_idle_timeout` de PgBouncer.

À éviter derrière PgBouncer :
- `LISTEN/NOTIFY` ;
- les verrous consultatifs de session (`pg_advisory_lock`) ;
- `SET` hors transaction.

Réglages de départ : `pool_mode = transaction`, `default_pool_size = 20`, `max_client_conn = 500`.
Migrations et `pg_dump` passent **directement** par Postgres, sans PgBouncer.

## 4. Requêtes et index

### 4.1 pg_stat_statements

**Activation locale** : `docker-compose.yml` charge déjà le module
(`shared_preload_libraries=pg_stat_statements`, `pg_stat_statements.track=top`,
`track_io_timing=on`). `docker/postgres/init/01-pg-stat-statements.sql` crée l'extension à la
création du volume.

**Base existante, en local ou en production** :
1. Ajouter `shared_preload_libraries = 'pg_stat_statements'` dans la configuration du serveur, puis
   redémarrer Postgres.
2. Lancer `CREATE EXTENSION IF NOT EXISTS pg_stat_statements;` en superutilisateur, dans la base
   de l'application.

**Lecture** : chaque lundi, après le pic du dimanche. Les 15 requêtes qui coûtent le plus de temps
total :

```sql
SELECT round(total_exec_time::numeric / 1000, 1) AS total_s,
       calls,
       round(mean_exec_time::numeric, 2)         AS mean_ms,
       round(100.0 * shared_blks_hit / nullif(shared_blks_hit + shared_blks_read, 0), 1) AS hit_pct,
       left(query, 160)                           AS query
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY total_exec_time DESC
LIMIT 15;
```

Ensuite :
1. prendre chaque requête en tête et faire `EXPLAIN (ANALYZE, BUFFERS)` avec des valeurs réelles ;
2. corriger ;
3. `SELECT pg_stat_statements_reset();`, puis mesurer la semaine suivante.

Le texte des requêtes est normalisé (`$1`, `$2`) : aucune donnée personnelle n'y apparaît.

### 4.2 Audit des lectures fréquentes (27/09/2026)

On n'a rien pu mesurer ici : il n'y a pas de trafic réel. L'audit porte sur les selectors les plus
appelés. On n'ajoute que les index composites manquants **évidents**.

| Lecture | Requête | Index | Décision |
|---|---|---|---|
| Lectures du jour | `LiturgicalDate(date, zone)`, puis `Reading` par `liturgical_date` | Unicités `(date, zone)` et `(liturgical_date, type, citation)` | Couvert. |
| Méditation du jour | `Article` par `scope_node`, `content_type`, `status`, `published_at__date` | `(scope_node, status, -published_at)` | Couvert. Voir la remarque (a). |
| Notifications non lues | `Notification(user, is_read)` trié par `-created_at`, compteur | `notif_user_unread_idx (user, is_read, -created_at)` | Couvert. |
| Messages d'une conversation | `Message(conversation)` trié par `-created_at`, curseur | `msg_conv_created_idx (conversation, -created_at)` | Couvert. |
| Non lus par conversation | Sous-requête par conversation dans la liste, puis `message_mark_read` à chaque ouverture | Aucun index sur `read_at` | **Ajouté** : `msg_conv_unread_idx (conversation, sender) WHERE read_at IS NULL AND deleted_at IS NULL`. L'index partiel ne contient que les messages en attente, donc il reste petit. Créé `CONCURRENTLY` (migration `messaging.0004`). |
| Interlocuteurs (présence) | `Conversation` par `participant_a` ou `participant_b`, `MessageBlock` | Clés étrangères et `(participant_x, -last_message_at)` | Couvert. |
| Appareils push | `PushDevice(user)` actifs | Clé étrangère `user` | Couvert. Quelques lignes par personne. |
| Dons par nœud et par mois (synthèse) | `Donation` joint à `Fund(node)`, filtré sur `status = confirme` et le mois de `confirmed_at` | `(fund, status)` | **À faire par le lot des dons** (b). |
| Opérations d'une paroisse | `Donation` joint à `Fund(node)`, trié par `-created_at` | `(fund, status)` | **À faire par le lot des dons** (b). |
| Quêtes d'une paroisse | `CashCollection(node)`, avec ou sans `status`, trié par `-mass_date` | Clé étrangère `node`, `status` seul | **À faire par le lot des dons** (b). |

(a) Le filtre `published_at__date=day` applique `AT TIME ZONE` à la colonne. L'index s'utilise
alors sur `(scope_node, status)`, mais pas sur la date. Le nombre de méditations reste faible, donc
on ne touche à rien. Si la requête monte dans `pg_stat_statements`, on la réécrit en intervalle :
`published_at >= début du jour` et `< lendemain`.

(b) Le module `donations` appartient à un autre lot : B2 ne crée pas de migration dans cette app.
Recommandations pour ce lot :
- `Index(fields=["fund", "status", "confirmed_at"])` remplace `(fund, status)`, dont il couvre le
  préfixe. Écrire aussi le filtre du mois en intervalle
  (`confirmed_at__gte=début`, `confirmed_at__lt=fin`), et non `confirmed_at__date`, pour que
  l'index serve la date.
- `Index(fields=["fund", "-created_at"])` pour la liste des opérations.
- `Index(fields=["node", "status", "-mass_date"])` sur `CashCollection` pour « À traiter » et la
  liste des quêtes.
- Toutes ces créations passent par `AddIndexConcurrently`, dans une migration `atomic = False`.

### 4.3 Règles pour les index suivants

- Un index se justifie par une requête qui apparaît dans `pg_stat_statements`, et par un `EXPLAIN`
  qui montre un parcours séquentiel ou un tri coûteux.
- Un index partiel convient quand le filtre ne garde qu'une petite part de la table : non lus, en
  attente, planifiés.
- En production, on crée toujours avec `AddIndexConcurrently`. On ne supprime un index que si
  `pg_stat_user_indexes.idx_scan` reste à 0 pendant 30 jours.

## 5. Partitionnement

Seulement pour la table qui grossit vite : les **événements d'écoute** (`audio_play_event`, lot B3).
- Volume attendu : 50 000 utilisateurs × 10 événements par jour, soit environ 180 millions de lignes
  par an.
- Partitionnement déclaratif **par mois** sur `occurred_at`, avec la clé primaire
  `(id, occurred_at)`. Une tâche Beat mensuelle crée la partition du mois suivant, en `reco` ou
  `default`.
- Chaque nuit, les données brutes sont agrégées dans une table non partitionnée (écoutes par piste,
  par jour et par paroisse). Les partitions de plus de 13 mois sont **détachées puis supprimées**
  (`DETACH PARTITION … CONCURRENTLY`), jamais purgées par `DELETE`.
- Aucune autre table n'est partitionnée : ni les dons, ni les messages, ni les notifications.
  Pour les notifications, on purge plutôt les lues de plus de 6 mois quand la table dépasse
  10 millions de lignes.

## 6. Files Celery

Les files sont déclarées dans `config/settings/celery.py`.

| File | Contenu | Worker |
|---|---|---|
| `default` | E-mails, notifications, push, webhooks, tâches courtes. Lit aussi l'ancienne file `celery` au déploiement. | `celery -Q default,celery` |
| `media` | Encodage audio ffmpeg (B3), par exemple `apps.audio.tasks.audio_transcode_task`. | `celery -Q media --concurrency=1..2 --prefetch-multiplier=1` |
| `reco` | Recommandations précalculées (B3, B4), par exemple `apps.bible.tasks.bible_reco_recompute_task`. | `celery -Q reco --concurrency=1` |

Routage d'une tâche, par ordre de priorité :
- `@shared_task(queue="media")` dans le décorateur ;
- sinon, le nom de la tâche :
  - `apps.*.tasks_media.*`, `apps.*.tasks.media_*` ou `*transcode*` vont dans `media` ;
  - `apps.*.tasks_reco.*`, `apps.*.tasks.reco_*` ou `apps.*.tasks.*_reco_*` vont dans `reco`.

Les workers sont définis dans `Procfile` et `docker-compose.yml` (services `celery`,
`celery-media`, `celery-reco`).

Une file peut livrer un message deux fois : **toute tâche est idempotente**. Par exemple, le push
porte une clé de regroupement, et l'encodage vérifie l'état de la piste avant de travailler.

## 7. Observabilité

**`/metrics`** (django-prometheus) :
- Accès : adresse du collecteur dans `METRICS_ALLOWED_CIDRS` (lue dans `REMOTE_ADDR`), ou en-tête
  `Authorization: Bearer <METRICS_TOKEN>`.
- Une requête qui arrive par Traefik porte `X-Forwarded-For` : elle exige le jeton, même depuis le
  réseau Docker.
- Sinon, la réponse est 404.
- Prometheus interroge le conteneur `django:8000` directement, sur le réseau interne :

  ```yaml
  scrape_configs:
    - job_name: jangubi
      metrics_path: /metrics
      static_configs: [{targets: ["django:8000"]}]
      authorization: {credentials_file: /etc/prometheus/jangubi-token}
  ```

**Alertes de départ** :

| Signal | Seuil | Durée |
|---|---|---|
| Taux de réponses 5xx (`django_http_responses_total_by_status_view_method`) | > 1 % | 5 min |
| p95 de l'API | > 1 s | 10 min |
| File `media` (exportateur RabbitMQ ou Flower) | > 20 messages | 10 min |
| Paiements en attente sans IPN (plan §4) | aucun IPN depuis 30 min | — |

**Flower** :
- Commande : `docker compose --profile ops up flower`.
- Adresse : `http://127.0.0.1:5555`, locale seulement. Définir `FLOWER_BASIC_AUTH`.
- Ne jamais l'exposer par Traefik sans authentification.

**Traces OpenTelemetry** : plus tard, quand Sentry et les métriques ne suffiront plus pour
localiser un goulot.

## 8. Pannes et sauvegardes

Rappel du plan §2, ligne 8 :
- sauvegarde Postgres quotidienne et restauration à un instant donné (WAL-G vers le stockage objet),
  restauration testée chaque trimestre ;
- healthchecks Traefik et redémarrage automatique ;
- pas de multirégion pour l'instant.
