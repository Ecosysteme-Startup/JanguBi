# L0 — Rapport de baseline (25/09/2026)

## 1. État git constaté

| Branche | Local | origin | Constat |
|---|---|---|---|
| `develop` | `1ccc7e7` (12 commits de retard) | `fa12089` | Local réaligné sur `origin/develop` |
| `fix/audit-beta` | `3c43f0e` | — (jamais poussée) | **Contient `origin/develop`** + 3 commits (escalade de privilèges RoleAssignment, lien d'activation, seed dans `init-all`). Les 12 autres commits « d'avance » sur l'ancien `develop` local étaient déjà sur `origin/develop`. Fusion sans conflit. |
| `stage` | réaligné | `2986be9` | Contient `origin/develop` entièrement (20 commits de promotion en plus) |
| `main` | réaligné | `f81ab7a` | 41 commits de retard sur `stage`, 4 commits propres (merges de PR, `update cors`, correctif `trigger-deploy`) |

**Plan de fusion proposé**

1. PR `fix/audit-beta` → `develop` (3 commits).
2. PR `chore/v1-l0-preparation` → `develop` (empilée sur `fix/audit-beta`).
3. Tag `pre-v1` sur `develop` **avant** le merge de L0, c.-à-d. après le merge de `fix/audit-beta`.
4. `stage` → `main` : PR de promotion habituelle après recette (hors L0). Les 4 commits propres à `main` sont des merges et un correctif CI déjà repris sur `develop` ; à vérifier au moment de la PR.

**Branches archivées** : 31 branches locales entièrement fusionnées dans `origin/develop` sont devenues des tags `archive/<nom>` puis ont été supprimées localement (restauration : `git branch <nom> archive/<nom>`). Une seule n'était pas fusionnée : `feat/srs-completion` (1 commit, `a4229d1`, app `spiritual` — module gelé) → `archive/feat/srs-completion`. Les branches distantes (`bugfix/aelf-dailytext-null-title`, `feat/docker-multistage`, `feat/rag-semantique-gratuit`, `features/add-tests-app`, `features/usermanagement`) ne sont pas touchées : leur suppression demande un push.

## 2. Baseline des tests

- `make act` (job `build` : ruff, mypy, pytest dans le runner) : **vert**, 1 442 tests passés, 0 échec.
- Les échecs historiques de `docs/backlog/BUG-TESTS-001` (12) et `-002` (pagination messagerie instable) **ne se reproduisent plus** : ils ont été corrigés sur `develop` entre juin et septembre. Aucun `xfail` n'a été nécessaire. Les deux tickets peuvent être clos.

## 3. Correctifs de CI faits pendant L0

- `config/django/base.py` forçait `127.0.0.1:5432` dès que `GITHUB_WORKFLOW` était défini, en ignorant `DATABASE_URL` : `make act` tombait sur le Postgres local de la machine. Bloc supprimé (le workflow fournit déjà `DATABASE_URL`).
- Ports hôtes des services surchargeables (`vars.CI_PG_HOST_PORT`, `vars.CI_REDIS_HOST_PORT`) ; `.actrc` les fixe à 55432 / 56379. Sur GitHub, les variables n'existent pas : comportement inchangé.

## 4. Gel des modules (ADR-006)

`JANGUBI_MODULES` (défaut = périmètre V1, surcharge par variable d'environnement). Gelés : `donations`, `mass_intentions`, `transfers`, `spiritual`, `tv`, `rag`, `clergy_accounts`, `testing_examples`, `bible.avance` (Lectio, plans de lecture, notes d'homélie), `liturgy.heures` (Laudes → Complies, `offices/<id>`), `rosary.communautaire`. Aucune tâche Beat actuelle n'appartient à un module gelé. La suite de tests active tous les modules (le code gelé reste maintenu).

⚠️ **Impact front** : le front actuel appelle encore certaines routes gelées (Liturgie des Heures, intentions, dons, chapelet communautaire). En production, elles répondront 404 dès le déploiement de L0. Pour les garder actives le temps de la refonte du front, définir `JANGUBI_MODULES` dans l'environnement du serveur.

## 5. À faire par le mainteneur

- Pousser `fix/audit-beta` et `chore/v1-l0-preparation`, ouvrir les PR (brouillon d'abord : plus de minutes consommées).
- Poser le tag `pre-v1`.
- `make hooks` dans chaque clone.
