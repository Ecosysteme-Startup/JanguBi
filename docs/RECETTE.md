# Environnement de recette (staging)

La recette fait tourner **l'image de production** avec les réglages `config.django.staging`, sur le
serveur partagé de l'écosystème (production et recette cohabitent), orchestré par le dépôt
[`Ecosysteme-Startup/Infrastructure`](https://github.com/Ecosysteme-Startup/Infrastructure). Elle sert à valider les écrans web et
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

## Où et comment elle tourne

Tout le déploiement vit dans le dépôt **Infrastructure**, dossier `apps/jangubi/` : compose,
variables (`envs/staging/jangubi.env.sops`, chiffré), realm Keycloak `jangubi-staging`, bucket
MinIO `jangubi-staging`, sauvegardes et test de fumée. Keycloak, MinIO et Traefik y sont
**partagés** avec les autres applications ; ce dépôt-ci ne fournit que l'image
(`docker/production.Dockerfile`) et la configuration d'identité (`deploy/keycloak/`).

| Adresse | Rôle |
|---|---|
| https://jangubi.ceac.dev | web (Next) |
| https://api-jangubi.ceac.dev/api/v1/ | API HTTP, WebSocket et SSE (daphne) |
| https://api-jangubi.ceac.dev/api/health/ | santé (base + Redis) |
| https://accounts.ceac.dev/realms/jangubi-staging | émetteur OIDC |

Première mise en recette et livraisons : `apps/jangubi/README.md` du dépôt Infrastructure.
En bref : un push sur la branche `stage` construit l'image (runner `ceac`) et prévient
l'Infrastructure ; sur le serveur, `make deployer APP=jangubi ENV=staging`.

### Seeds

Deux commandes, dans le conteneur de l'API (`make shell APP=jangubi ENV=staging` depuis
`/opt/mctn/infrastructure`) :

```bash
python manage.py seed_prod                               # données réelles (aussi en production)
SEED_ALLOWED=true python manage.py seed_recette          # recette complète (échelle moyenne)
SEED_ALLOWED=true python manage.py seed_recette --reset  # retire les données de test, MANUEL uniquement
```

`seed_recette` = `seed_prod` + personnes de démonstration + monde de test réaliste (12 paroisses,
5 000 fidèles, dons sur douze mois, sonothèque encodée par le vrai pipeline) + musique de démo.
Musique de démo, **une seule fois** : RAR décompressé dans `seed_assets/`, puis
`python manage.py prepare_musique_demo --publier` (dossier privé `seed-assets/musique-demo/` du bucket de l'app) ; les
`seed_recette` suivants la reprennent seuls. Détails : `docs/DONNEES-DE-TEST.md`.

Les comptes Keycloak se gèrent depuis l'administration de l'app (synchronisés avec le realm) :
ils ne sont pas créés par ces commandes.

## Comptes

Consoles Keycloak et MinIO : celles du socle partagé (`accounts.ceac.dev`, `console-s3.ceac.dev`),
accès gérés dans le dépôt Infrastructure.

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


## Poste de développement

Pour travailler en local, utiliser la pile de dev (`docker-compose.yml`, voir le README) ; il
n'existe plus de recette autonome dans ce dépôt, pour éviter de la lancer par erreur sur le
serveur.
