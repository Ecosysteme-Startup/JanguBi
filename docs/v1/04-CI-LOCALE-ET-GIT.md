# Jàngu Bi — Git flow et CI locale (`act`)

> **Règle d'or : aucun push vers `develop`, `stage` ou `main`, ni aucune PR vers ces branches, sans `make act` vert en local.**
> Chaque push sur ces branches consomme des minutes GitHub Actions. Un push sur `stage` **livre en recette** (`livraison-recette.yml` → `Ecosysteme-Startup/Infrastructure`) : un push vert mais non testé en profondeur part chez les testeurs.

---

## 1. Branches

| Branche | Rôle | Qui y pousse | Déploie |
|---|---|---|---|
| `main` | Production | PR depuis `stage` après recette, tag `vX.Y.Z` | Non : la production se promeut dans l'Infrastructure |
| `stage` | Recette / pilote | PR depuis `develop` en fin de lot (L3, L6a, L9) | Oui (recette, `livraison-recette.yml`) |
| `develop` | Intégration | PR depuis les branches `feat/`, `fix/`, `chore/` | Non (CI qualité seule) |
| `feat/v1-lX-<sujet>` | Travail d'un lot | Le développeur ou Claude Code | Non (CI non déclenchée par le push) |
| `hotfix/<sujet>` | Correctif de production | Depuis `main`, PR vers `main` **et** `develop` | — |

**Conventions**
- Commits au format Conventional Commits, en français, comme l'historique existant : `feat(hierarchy): arbre des nœuds et types paramétrables`.
- Une PR = un sous-lot cohérent (≤ 800 lignes hors migrations et tests si possible), en squash merge vers `develop`.
- Merge commit (sans squash) pour `develop → stage` et `stage → main`, afin de garder l'historique.
- Jamais de `--force` sur `develop`, `stage` ou `main`.

---

## 2. La CI GitHub (rappel)

`.github/workflows/django.yml` (qualité seule) se déclenche sur push vers `main` et `develop` et sur PR vers `main`, `develop` et `stage` :

| Job | Contenu | Se lance avec `act` ? |
|---|---|---|
| `build` | Installation, `ruff check apps/`, `mypy apps/`, `pytest apps/` avec Postgres (pgvector) et Redis en services | **Oui, toujours** : c'est le gate |

La livraison en recette (`.github/workflows/livraison-recette.yml`, push `stage` et tags `v*`, runner `ceac`) construit l'image et notifie `Ecosysteme-Startup/Infrastructure`. **Jamais via `act`** ; pour tester le Dockerfile : `make ci-docker` (build local sans push). L'ancien déploiement par `trigger-deploy` vers `Kamal-Fils/infrastructure` est supprimé (30/09/2026).

---

## 3. Installer `act` (une fois)

```bash
# Linux
curl -s https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash -s -- -b /usr/local/bin
act --version

# Docker doit tourner (l'utilisateur doit appartenir au groupe docker)
docker info >/dev/null && echo "Docker OK"
```

Fichier **`.actrc`** à la racine de `JanguBi/` (versionné) :

```
-P ubuntu-24.04=catthehacker/ubuntu:act-24.04
--pull=false
--rm
```

Fichier **`.secrets.example`** (versionné, sans valeur). Le vrai `.secrets` est dans `.gitignore` et ne sert qu'à `ci-docker-act`, qu'on ne lance normalement pas.

> Premier lancement : l'image `catthehacker/ubuntu:act-24.04` pèse plusieurs Go. Téléchargez-la une fois (`docker pull catthehacker/ubuntu:act-24.04`), puis `--pull=false` évite de la retélécharger.

---

## 4. Les commandes

```bash
make ci-list      # liste les jobs vus par act
make act          # = act push --job build : ruff + mypy + pytest, exactement comme la CI
make ci-docker    # build local de l'image de prod (docker/production.Dockerfile), SANS push
```

Simuler une PR vers `develop` (même job, autre événement) :

```bash
act pull_request -P ubuntu-24.04=catthehacker/ubuntu:act-24.04 --job build
```

**Plan B** si `act` ne peut pas tourner (machine sans Docker ou sans réseau dans le conteneur) :

```bash
source .venv/bin/activate
ruff check apps/ config/ && mypy apps/ config/
make up && make test          # pytest dans la stack Docker (DB réelle)
make ci-docker                # si le Dockerfile ou les dépendances ont changé
```

Le plan B est acceptable **uniquement** si les trois étapes sont vertes. Dans ce cas, indiquez « gate local : plan B » dans la description de la PR.

---

## 5. Hook `pre-push` (filet de sécurité)

Fichier `scripts/git-hooks/pre-push`, à installer avec `make hooks` (`git config core.hooksPath scripts/git-hooks`) :

```bash
#!/usr/bin/env bash
# Bloque tout push vers develop/stage/main si le gate CI local n'est pas vert.
protected='^(develop|stage|main)$'
while read -r local_ref local_sha remote_ref remote_sha; do
  branch="${remote_ref#refs/heads/}"
  if [[ "$branch" =~ $protected ]]; then
    echo "→ Push vers $branch : exécution du gate CI local (make act)…"
    if ! make act; then
      echo "✗ make act a échoué : push annulé. Corrigez, ou utilisez le plan B (voir docs/v1/04-CI-LOCALE-ET-GIT.md)."
      exit 1
    fi
  fi
done
exit 0
```

Le contournement `git push --no-verify` est réservé aux cas documentés (panne de Docker avec plan B vert), avec une mention dans la PR.

---

## 6. Économiser les minutes GitHub Actions (modifications du workflow, lot L0.6)

À appliquer dans `.github/workflows/django.yml` :

```yaml
on:
  push:
    branches: [main, develop, stage]
    tags: ['v*']
    paths-ignore: ['docs/**', '**/*.md', 'graphify-out/**']
  pull_request:
    branches: [main, develop, stage]
    types: [opened, synchronize, reopened, ready_for_review]
    paths-ignore: ['docs/**', '**/*.md', 'graphify-out/**']

jobs:
  build:
    if: github.event_name != 'pull_request' || github.event.pull_request.draft == false
```

- Les PR en brouillon ne consomment plus de minutes.
- Les changements purement documentaires ne déclenchent ni la CI ni le déploiement.
- `concurrency` avec `cancel-in-progress` est déjà en place.

Le même principe (act avant push, `paths-ignore`, PR brouillon) s'applique au frontend (`JanguBiUI/.github/workflows/nextjs.yml`) avec son propre job de build.

---

## 7. Checklist avant chaque PR vers `develop`

- [ ] `make act` vert (ou plan B complet, mentionné)
- [ ] `make ci-docker` vert si `requirements/`, `docker/` ou `settings` ont changé
- [ ] Migrations : aller-retour testé (`migrate <app> <précédente>` puis `migrate`)
- [ ] `python manage.py spectacular --file schema.yml` régénéré et commité
- [ ] Description : lot, exigences couvertes (EF-…), migrations, captures OpenAPI
