# Rapport de fin de chantier — refonte backend V1 (L0 → L9)

> 25/09/2026. Tout est **local** : aucune branche poussée, aucune PR ouverte, rien de fusionné.

## 1. Branches (empilées, dans l'ordre de fusion)

| Ordre | Branche | Contenu |
|---|---|---|
| 0 | `fix/audit-beta` | correctifs de l'audit pré-beta (escalade de privilèges, lien d'activation, renvoi, seed dans `init-all`) |
| 1 | `chore/v1-l0-preparation` | gel des modules (`JANGUBI_MODULES`), CI locale `act`, hook pre-push, rapport de baseline |
| 2 | `feat/v1-l1-hierarchy` | arbre des juridictions (treebeard), lieux, horaires, import CSV, profils de hiérarchie |
| 3 | `feat/v1-l2-authz` | offices, nominations, capacités (`peut`, `HasCapability`), audit, reprise des anciens droits |
| 4 | `feat/v1-l3-keycloak` | Keycloak OIDC, MFA staff, tickets WebSocket, migration des comptes, realm versionné |
| 5 | `feat/v1-l4-ma-paroisse` | annonces et événements par nœud, fil du fidèle, préférences et silences de notification |
| 6 | `feat/v1-l5-actes` | demandes d'actes V1 (cycle, file par nœud, SLA, rappels, purge des pièces) |
| 7 | `feat/v1-l6a-pretre-confessions` | prêtres joignables, disponibilités, majorité, admin sans contenu ; app `confessions` |
| 8 | `docs/v1-l6b-e2e-etude` | étude E2E + ADR-014 **proposée** (aucun code) |
| 9 | `feat/v1-l8-dashboards` | tableaux de bord par nœud et plateforme |
| 10 | `feat/v1-l7-parole` | calendrier liturgique local, `LITURGY_SOURCE`, `BIBLE_EDITION`, provenance du chapelet, méditation |
| 11 | `feat/v1-l9-conformite` | consentement, export, suppression du compte, registre des traitements, correctifs de sécurité |

Chaque lot : tests d'abord, revue `django-reviewer` (+ `database-reviewer` pour les migrations), correctifs de revue commités, `act push --job build` vert sur l'instantané du lot. Suite complète à la tête : 1 327 tests verts, ruff et mypy propres. Migrations testées aller-retour.

## 2. Ruptures de contrat d'API (ADR-013)

Le front actuel **ne doit pas** être redéployé sur ce backend : chaque lot a remplacé les routes historiques de son app (listes détaillées dans `docs/v1/conception/L*-*.md`). En résumé : `news`, `agenda`, `documents`, `messaging` (profils prêtres, inter-clergé gelé), `dashboards` (toutes les anciennes routes), `liturgy` (relais AELF retirés, `/liturgy/{date}/`). Le contrat de référence est `schema.yml`.

## 3. Réglages de bascule

| Réglage | Défaut | À faire |
|---|---|---|
| `JANGUBI_MODULES` | modules V1 | les routes gelées renvoient 404 |
| `KEYCLOAK_ENABLED` / `LEGACY_JWT_ENABLED` | faux / vrai | passer à vrai / faux dès que le front V1 est sur Keycloak (avertissement au démarrage sinon) |
| `LITURGY_SOURCE` | `crampon_refs` | `aelf` seulement avec l'accord écrit de l'AELF |
| `BIBLE_EDITION` | vide | `crampon1923` après l'import de la Crampon |
| `CONSENT_CURRENT_VERSION` | `2026-09` | aligner sur la version publiée des CGU et de la politique |
| `DJANGO_ADMIN_ENABLED` | faux en production | ouvrir seulement derrière une restriction réseau (pas de MFA sur l'admin) |
| `LITURGY_*_ON_SUNDAY` | Épiphanie et Saint-Sacrement le dimanche, Ascension le jeudi | à confirmer par la Conférence épiscopale |

## 4. Décisions qui te reviennent

1. **E2E (ADR-014)** : chiffré à 13–18 jours, au-delà du seuil de 12. Proposition : report après le pilote, avec une mention de transparence.
2. **Contraction des migrations** (`docs/v1/conception/L9-contraction.md`) : non exécutée. Préalables : sort des modules gelés, bascule Keycloak effective, sauvegarde restaurée.
3. **Bible Crampon** : confirmer le statut de domaine public, produire le JSON, importer (procédure dans `L7-parole.md`). Le texte actuellement en base vient du scraping AELF et ne doit plus être servi.
4. **Registre des traitements** (`docs/v1/conformite/registre-des-traitements.md`) : compléter les `[À COMPLÉTER]` (responsable, hébergeur et pays, prestataire e-mail, durées de conservation) puis déposer à la CDP.

## 5. Actions d'infrastructure (revue de sécurité)

- Admin Django : restreindre au réseau d'administration si elle est ouverte.
- Vérifier `FILE_UPLOAD_STORAGE=S3`, bucket privé et URL présignées courtes en production.
- Monter `SECURE_HSTS_SECONDS` à un an une fois TLS stable.
- Ne pas journaliser les chaînes de requête de `/ws/` tant que l'ancien JWT est accepté.
- Sauvegardes Postgres chiffrées avec restauration testée, Uptime Kuma (hors dépôt backend).

## 6. Points connus, non traités

- Les vues d'administration historiques de `users` (listes, rôles, adhésions) utilisent encore l'ancien modèle de rôles : à retirer à l'étape 1 de la contraction.
- CSRF désactivé pour l'authentification par session des API (choix historique documenté) ; pas de permission par défaut globale.
- Les références des lectures du jour viennent encore de l'API AELF (seuls les textes sont remplacés).
- Seed du pilote (nominations réelles de la paroisse Saint-Dominique) : étape humaine, avec les vraies personnes.
