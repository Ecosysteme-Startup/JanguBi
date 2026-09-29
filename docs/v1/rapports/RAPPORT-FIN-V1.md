# Rapport de fin de chantier — backend V1

> 25/09/2026. Tout est fusionné dans `develop` **en local** ; rien n'est poussé.

## 1. Contenu

| Lot | Livré |
|---|---|
| L0 | CI locale `act`, hook pre-push, gel des sous-modules par réglage |
| L1 | Arbre des juridictions (treebeard), lieux de culte, horaires, import CSV, profil « senegal » |
| L2 | Offices, nominations, capacités (`peut`, `HasCapability`), journal d'audit |
| L3 | Keycloak (OIDC, MFA staff, tickets WebSocket, migration des comptes) |
| L4 | Annonces et événements par nœud, fil du fidèle, préférences et silences de notification |
| L5 | Demandes d'actes V1 (cycle, file par nœud, SLA, rappels, purge des pièces) |
| L6a | Parler à un prêtre (joignabilité, disponibilités, majorité, admin sans contenu) ; rendez-vous de confession |
| L6b | Étude E2E (ADR-014 : report après le pilote) |
| L7 | Calendrier liturgique local, `LITURGY_SOURCE`, `BIBLE_EDITION`, provenance du chapelet, méditation du jour |
| L8 | Tableaux de bord par nœud et plateforme |
| L9 | Consentement, export, suppression du compte, registre des traitements, revue de sécurité |
| ADR-015 | Keycloak seule authentification (SimpleJWT, `jwt_key`, routes `auth/` et `users/` retirés) |
| ADR-016 | Contraction : ancien modèle et modules hors V1 supprimés, migrations remises à zéro |

Chaque lot : tests d'abord, revue (`django-reviewer`, `security-reviewer`, `database-reviewer`), correctifs de revue, `act push --job build` vert.

## 2. Mise en route d'un environnement

La base doit être **recréée** (historique des migrations remis à zéro, ADR-016) :

```bash
make down-v
make up && make init-all && make seed-demo
make kc-up && manage.py migrate_users_to_keycloak --apply   # si des comptes existent
```

## 3. Réglages

| Réglage | Défaut | Remarque |
|---|---|---|
| `KEYCLOAK_ENABLED` | vrai | synchronisation avec l'administration Keycloak (rôle staff, suppression de compte) |
| `LITURGY_SOURCE` | `crampon_refs` | `aelf` seulement avec l'accord écrit de l'AELF |
| `BIBLE_EDITION` | vide | `crampon1923` une fois la Crampon importée ; avertissement au démarrage tant que c'est vide |
| `CONSENT_CURRENT_VERSION` | `2026-09` | aligner sur la version publiée des CGU et de la politique |
| `DJANGO_ADMIN_ENABLED` | faux en production | l'admin Django n'a pas de MFA |
| `LITURGY_*_ON_SUNDAY` | Épiphanie et Saint-Sacrement le dimanche, Ascension le jeudi | usages à confirmer par la Conférence épiscopale |

## 4. Hors du code (à faire par l'équipe)

- Front V1 : Auth.js (Keycloak), tickets WebSocket, nouveau contrat (`schema.yml`).
- Bible Crampon : confirmer le domaine public, produire le JSON, `import_bible … --source crampon1923` (procédure dans `conception/L7-parole.md`). Le texte actuellement importé par `make init-data` vient de l'AELF.
- Registre des traitements : compléter les champs `[À COMPLÉTER]` et déposer à la CDP.
- Infrastructure : restreindre l'admin Django au réseau d'administration si elle est ouverte ; bucket S3 privé ; HSTS à un an ; sauvegardes Postgres chiffrées avec restauration testée ; Uptime Kuma.
