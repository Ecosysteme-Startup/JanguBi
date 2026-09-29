# CLAUDE.md — JanguBi (Backend Django)

Backend de la plateforme **Jàngu Bi** — Django 5.2 + DRF, ASGI (Daphne), Celery, pgvector, Django Channels.

> Voir le CLAUDE.md racine (`../CLAUDE.md`) pour les commandes Make, l'infrastructure Docker, et les règles d'orchestration agents/skills.

---

## Architecture — HackSoft Styleguide (CRITIQUE)

Chaque app suit ce pipeline strict. **Ne jamais sauter ni croiser les couches.**

```
models.py      → Schéma DB uniquement. Aucune logique métier.
services.py    → Toutes les écritures. Toujours @transaction.atomic.
selectors.py   → Toutes les lectures (QuerySets). Aucune écriture.
serializers.py → Validation input + mise en forme output. Aucune logique.
apis.py        → Couche HTTP uniquement. Appelle services/selectors. Aucun ORM.
permissions.py → Classes de permission DRF (niveau objet).
tasks.py       → Tâches Celery. Import services dans le corps de la fonction.
```

### Règles fondamentales

- **Erreurs domaine** → `raise ApplicationError(...)` depuis `apps.core.exceptions`. Les APIs attrapent avec `_error()`.
- **Emails** → Jamais SMTP direct. Créer un record `Email`, dispatcher via `transaction.on_commit(lambda: email_send_task.delay(email.id))`.
- **Fichiers** → Un fichier est valide uniquement quand `upload_finished_at` est défini (`file.is_valid`).
- **Toutes les mutations** → keyword-only args (`*` separator), retourner l'objet modifié.
- **Tout endpoint** → `@extend_schema` obligatoire (drf-spectacular). Pas d'endpoint non documenté.

---

## Vérification AVANT push (CI locale — OBLIGATOIRE)

> **Règle :** ne jamais pusher sur `develop` / `stage` / `main` sans avoir fait
> passer le gate CI **en local d'abord**. Le job `build` de la CI GitHub
> (install + ruff + mypy + pytest) est ce qui conditionne le déploiement : s'il
> échoue, rien ne se déploie. On veut attraper ça **avant** le push, pas après.

```bash
make act          # = act push --job build  → rejoue EXACTEMENT le job CI (ruff + mypy + pytest) en conteneur
make ci-docker    # build l'image de prod (docker/production.Dockerfile) sans push — valide le Dockerfile
```

Si `make act` ne peut pas s'exécuter (le conteneur act n'a **pas de réseau** →
`yarn/pip install` échoue avec `ENETUNREACH`, cas d'un sandbox sans Internet),
rejouer le gate **directement**, ce qui couvre les mêmes étapes :

```bash
source .venv/bin/activate         # le venv hôte a ruff + mypy (pas besoin de DB)
ruff check apps/ config/
mypy apps/ config/
make test                          # = docker compose exec django pytest  (a besoin de la stack `make up` pour la DB)
```

- **ruff + mypy** tournent sur l'hôte sans DB.
- **pytest** a besoin d'une DB Postgres : soit via `make act` (conteneur), soit
  via `make up` puis `make test` (stack Docker complète). Pas de DB locale → pas
  de pytest local : dans ce cas, **pusher uniquement après** ruff+mypy verts, et
  surveiller le run CI GitHub (`gh run watch`) — le déploiement est bloqué tant
  que le job `build` (pytest) n'est pas vert.

Ne pusher que si **tout est vert**. `main` ne se pousse qu'après revue de staging.

---

## Modèle de rôles (deux dimensions orthogonales)

### Dimension 1 — Rôles pastoraux (`PastoralRole` — à implémenter)

```python
class PastoralRole(models.TextChoices):
    ARCHEVEQUE = 'archeveque'
    EVEQUE     = 'eveque'
    PRETRE     = 'pretre'
    DIACRE     = 'diacre'
    RELIGIEUX  = 'religieux'
    FIDELE     = 'fidele'
```

### Dimension 2 — Rôles d'administration digitale (`UserRole` — existant)

```python
class UserRole(models.TextChoices):
    SUPER_ADMIN    = 'super_admin'
    PROVINCE_ADMIN = 'province_admin'
    DIOCESE_ADMIN  = 'diocese_admin'
    PARISH_ADMIN   = 'parish_admin'
    CHURCH_ADMIN   = 'church_admin'
    FIDELE         = 'fidele'
```

`IsAnyAdmin` → passe pour tous les rôles admin. `IsSuperAdmin` → super_admin uniquement.

---

## Modèle territorial (P1 BLOQUANT — pas encore implémenté)

```python
# apps/org/ à créer
Province → Diocese → Parish → BaseUser.primary_parish (FK)
```

Signal post_save sur `primary_parish` → auto-remplit `diocese` et `province` sur BaseUser.

---

## Apps existantes

| App | Status | Notes |
|---|---|---|
| `apps/users/` | ✅ | `BaseUser`, `Profile`, `UserRole` enum |
| `apps/authentication/` | ✅ | JWT, refresh, blacklist |
| `apps/bible/` | ✅ | Livres, chapitres, versets, pgvector |
| `apps/rosary/` | ✅ | Mystères, prières |
| `apps/liturgy/` | ✅ | Lectures AELF messe (pas Liturgie des Heures) |
| `apps/messaging/` | ✅ | Conversations Fernet-chiffrées, WebSocket Channels |
| `apps/documents/` | ✅ | 6 statuts, SLA, Celery escalade, emails bilatéraux |
| `apps/news/` | ✅ | Articles (1 type, pas les 3 SRS), scope global/diocese/parish |
| `apps/tv/` | ✅ | Vidéos, catégories |
| `apps/rag/` | ✅ | RAG pgvector + Gemini |
| `apps/files/` | ✅ | Upload direct ou pass-thru S3 |
| `apps/notifications/` | ✅ | Basique |
| `apps/availability/` | ⚠️ | Minister CRUD API non intégré dans `api/urls.py` |

## Features manquantes (priorité SRS)

| Feature | Priorité |
|---|---|
| Modèle territorial `Province/Diocese/Parish` | 🔴 P1 — BLOQUANT |
| `PastoralRole` sur `BaseUser` + migration | 🔴 P1 |
| `UserOnboardingState` + sélection paroisse obligatoire | 🔴 P1 |
| Liturgie des Heures (7 offices AELF) | 🔴 P1 |
| Chaîne validation comptes clergé | 🔴 P2 |
| `ContentType` 3 formats (Annonce/Article/LettrePastorale) | 🔴 P2 |
| Communication inter-clergé (`ClergicalMessage`) | 🔴 P2 |
| `MassIntention`, `DonationCampaign`, `DonationTransaction` | 🟡 P4-P5 |

---

## Agents Claude à utiliser — Backend

| Situation | Agent / Skill |
|---|---|
| Avant toute nouvelle app ou feature | `code-architect` |
| Comprendre du code existant avant modification | `code-explorer` |
| Écrire les tests avant d'implémenter | `django-tdd-assistant` |
| Review après chaque modification Django | `django-reviewer` |
| Tout ce qui touche auth/JWT/permissions/rôles | `django-auth-implementer` |
| Toute migration ou requête DB complexe | `database-reviewer` |
| Référence patterns HackSoft | skill `django-patterns` |
| Design d'un nouvel endpoint | skill `api-design` |
| Migration zéro-downtime | skill `database-migrations` |
| Vérification sécurité | skill `django-security` |
| Checklist avant merge | skill `django-verification` |

---

## Celery Beat — Tâches planifiées

| Tâche | Heure UTC |
|---|---|
| Fetch lectures AELF | 02:00 |
| Sync liturgie | 03:00 |
| Purge conversations expirées | 03:00 |
| Notif purge imminente | 03:30 |
| Purge comptes admin expirés | 04:00 |
| Auto-escalade documents | 08:00 |

---

## Ajouter une nouvelle app

```bash
# 1. Créer la structure
mkdir -p apps/<name>/migrations
touch apps/<name>/__init__.py apps/<name>/apps.py \
      apps/<name>/models.py apps/<name>/services.py \
      apps/<name>/selectors.py apps/<name>/serializers.py \
      apps/<name>/apis.py apps/<name>/urls.py \
      apps/<name>/admin.py apps/<name>/migrations/__init__.py

# 2. Enregistrer dans config/django/base.py LOCAL_APPS
# 3. Ajouter path() dans apps/api/urls.py
# 4. Générer + appliquer migrations
docker compose exec django python manage.py makemigrations <name>
docker compose exec django python manage.py migrate <name>
```
