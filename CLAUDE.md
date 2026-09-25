# CLAUDE.md — JanguBi (backend Django), refonte V1

Backend de **Jàngu Bi** : Django 5.2 + DRF, ASGI (Daphne), Channels, Celery (broker RabbitMQ), PostgreSQL + pgvector, Redis, MinIO, **Keycloak** (à partir du lot L3).

> **Source de vérité de la V1 : `docs/v1/`.** Lire `docs/v1/00-LIRE-D-ABORD.md` au début de chaque session.
> Les anciens SRS (`docs/archive/`) et `../memory/*.md` sont **obsolètes** : ne pas s'en servir comme référence.

---

## 1. Où on en est

- Refonte **sur place** (ADR-001), par lots L0 → L9 (`docs/v1/01-PLAN-BACKEND-V1.md`).
- Périmètre V1 : Parole · Ma paroisse · Demandes d'actes · Parler à un prêtre (+ rendez-vous de confession) · tableaux de bord · conformité.
- **Modules gelés** (ADR-006, réglage `JANGUBI_MODULES`) : `donations`, `mass_intentions`, `transfers`, `spiritual`, `tv`, `rag`, `clergy_accounts`, `testing_examples`, plus la Lectio et les plans de lecture (`bible`), les Offices des Heures (`liturgy`) et le chapelet communautaire (`rosary`). **Ne pas les modifier ni les réactiver** sans décision écrite.

## 2. Architecture — HackSoft Styleguide (CRITIQUE)

```
models.py      → Schéma DB uniquement. Aucune logique métier.
services.py    → Toutes les écritures. Toujours @transaction.atomic. Arguments keyword-only (*). Retourne l'objet.
selectors.py   → Toutes les lectures (QuerySets). Aucune écriture.
serializers.py → Validation d'entrée + mise en forme de sortie. Aucune logique.
apis.py        → HTTP uniquement. Appelle services/selectors. Aucun ORM.
permissions.py → Permissions DRF (HasCapability).
tasks.py       → Tâches Celery. Import des services dans le corps de la fonction.
```

- **Erreurs métier** : `raise ApplicationError(...)` (`apps.core.exceptions`).
- **E-mails** : jamais de SMTP direct. Créer un `Email` puis `transaction.on_commit(lambda: email_send_task.delay(email.id))`.
- **Fichiers** : un fichier n'est valide que si `upload_finished_at` est défini (`file.is_valid`).
- **Tout endpoint** : `@extend_schema` obligatoire. `schema.yml` est régénéré à chaque lot.
- **Audit** : les services sensibles écrivent un `AuditEvent` (jamais les vues).

## 3. Autorisation — offices et capacités (ADR-003)

> **L'ancien modèle `UserRole` × `PastoralRole` × `RoleAssignment` est abandonné.** Il reste lisible jusqu'au lot L9, mais **aucun nouveau code ne doit s'en servir**. `IsAnyAdmin` et `IsSuperAdmin` sont interdits dans les apps V1.

- Arbre des juridictions : `apps.hierarchy` (`NodeType`, `Node` en treebeard `MP_Node`, `PlaceOfWorship`, horaires).
- Offices et nominations : `OfficeType`, `OfficeAssignment` (datées, nommées par la bonne autorité).
- Capacités : catalogue **fermé** (`docs/v1/02-SRS-BACKEND-V1.md` §6.2).
- **Toute autorisation** : `peut(user, "actes.traiter", node)` ou la permission DRF `HasCapability("actes.traiter", node_resolver=...)`. Héritage sur le sous-arbre si l'office est `inherits_down`.
- Droits de base du fidèle (sans capacité) : SRS §6.1.
- Les files de travail appartiennent au **nœud**, pas à la personne (RG-04).

## 4. Authentification — Keycloak (ADR-004, livré en L3)

- OIDC : le front obtient le jeton (Auth.js, PKCE, client `jangubi-web`), l'API le valide via JWKS (`apps/authentication/keycloak.py`, audience `jangubi-api`), le WebSocket valide le même jeton au handshake (`?token=`, fermeture 4401 si invalide).
- Rôles de realm : `fidele`, `staff` (synchronisé depuis les nominations, MFA exigée), `platform_admin` (à la main, MFA exigée). **Aucune hiérarchie dans Keycloak.** L'API exige `amr ∋ otp` pour tout endpoint à capacité.
- Realm versionné : `infra/keycloak/realm-jangubi.json` ; `make kc-up` (http://localhost:8180), `make kc-export`, `make kc-test` (intégration réelle, hors CI).
- En tests : clé RSA et JWKS locaux, jamais de Keycloak réel en CI.
- **Bascule par réglage** : `KEYCLOAK_ENABLED=true` active Keycloak ; SimpleJWT reste accepté tant que `LEGACY_JWT_ENABLED=true` (transition du front). Ne pas étendre SimpleJWT ; `jwt_key` et les routes `/api/v1/auth/jwt/*` partent en L9.
- Migration des comptes : `manage.py migrate_users_to_keycloak [--apply]` (hachages pbkdf2 importés, pas de réinitialisation).

## 5. Règles métier à ne jamais enfreindre

- La demande d'acte va à la **paroisse du sacrement**. L'application ne délivre jamais l'acte (pas de PDF) : l'original est signé et scellé (RG-02, RG-03).
- **Pas de confession par message.** Le module `confessions` gère des rendez-vous en présentiel, **sans aucun champ de contenu** (RG-08).
- **Aucun accès administrateur au contenu des messages** (RG-09). Messagerie réservée aux majeurs (RG-13).
- Tableaux de bord au-dessus de la paroisse : agrégats uniquement (RG-11).
- Données religieuses = sensibles (loi 2008-12) : jamais dans les logs.

## 6. Vérification AVANT push — CI locale OBLIGATOIRE (ADR-010)

> **Aucun push ni PR vers `develop`, `stage` ou `main` sans `make act` vert.** Chaque push vert sur ces branches **déclenche un déploiement** et consomme des minutes GitHub Actions.

```bash
make act          # act push --job build : ruff + mypy + pytest, exactement comme la CI (Postgres/Redis en services)
make ci-docker    # build local de l'image de prod, SANS push (si requirements/, docker/ ou settings changent)
make hooks        # installe le hook pre-push qui lance make act vers develop/stage/main
```

- **Ne jamais lancer via act** les jobs `build-docker` (push DockerHub) et `trigger-deploy` (déploiement).
- Plan B si act ne tourne pas : `ruff check apps/ config/ && mypy apps/ config/`, puis `make up && make test`. À signaler dans la PR.
- Détails, branches et conventions : `docs/v1/04-CI-LOCALE-ET-GIT.md`.
- Claude Code travaille sur `feat/v1-lX-…`, ouvre une PR et **ne merge jamais** lui-même vers `develop`, `stage` ou `main`.

## 7. Migrations

- Stratégie **expand → migrate → contract**. Aucune suppression de colonne ou de table dans le lot qui bascule le code.
- Toute migration est réversible et testée aller-retour : `migrate <app> <précédente>` puis `migrate`.
- `database-reviewer` avant **et** après.

## 8. Agents et skills

| Situation | Agent / skill |
|---|---|
| Nouvelle app ou feature | `code-architect` (livrable dans `docs/v1/conception/`) |
| Comprendre l'existant | `code-explorer` |
| Tests d'abord | `django-tdd-assistant` |
| Revue après modification | `django-reviewer` |
| Auth, Keycloak, capacités | `django-auth-implementer` + skill `django-security` |
| Migrations, requêtes complexes | `database-reviewer` + skill `database-migrations` |
| Endpoints | skill `api-design` |
| Avant PR | skill `django-verification` + `make act` |

Prompts prêts à l'emploi : `docs/v1/05-PROMPTS-CLAUDE-CODE.md`.

## 9. Commandes utiles

```bash
make up / down / logs / shell
make makemigrations / migrate / check / test
make init-all                         # migrate + seed Bible/Rosaire/AELF + admin
docker compose exec django pytest apps/<app>/tests/test_services.py -v
docker compose exec django python manage.py spectacular --file schema.yml
docker compose exec django python manage.py seed_hierarchy_profile senegal   # à partir de L1
```

## 10. Ajouter une app

1. `apps/<name>/` avec `__init__`, `apps`, `models`, `services`, `selectors`, `serializers`, `apis`, `urls`, `permissions`, `admin`, `migrations/`, `tests/`.
2. L'ajouter à `LOCAL_APPS` (`config/django/base.py`) **et** à `JANGUBI_MODULES` si elle expose des routes.
3. `path("<name>/", include(...))` conditionnel dans `apps/api/urls.py`.
4. `makemigrations <name>`, `migrate`, tests, `make act`.
