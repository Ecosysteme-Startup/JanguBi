# L9 — Contraction des migrations : plan (non exécuté)

> Plan §2 L9 : suppression de `org.*`, `RoleAssignment`, `pastoral_role`, `UserRole`, `Membership`, SimpleJWT. Version du 25/09/2026.
> **Rien n'est supprimé dans ce lot.** Ces migrations détruisent des données et du code encore utilisés. Elles demandent trois décisions préalables et une sauvegarde vérifiée.

## 1. Pourquoi pas maintenant

Références restantes hors migrations et tests (comptage par app, `grep`) :

| Symbole | Apps V1 encore concernées | Apps gelées concernées |
|---|---|---|
| `apps.org` | `users` (5), `hierarchy` (migration de reprise, import), `core` (seed de démo), `api` | `donations`, `mass_intentions`, `transfers`, `spiritual`, `tv`, `clergy_accounts` |
| `RoleAssignment` / `UserRole` | `users` (11 fichiers : anciennes vues d'administration), `hierarchy` (repli `is_platform_admin` en JWT historique), `authentication`, `messaging` (1) | `clergy_accounts`, `mass_intentions`, `transfers`, `spiritual`, `tv` |
| `pastoral_role` | `users`, `authentication`, `messaging`, `hierarchy`, et `bible`, `liturgy`, `rosary` (sous-modules gelés) | idem |
| `Membership` | `users`, `messaging`, `hierarchy` | `donations`, `mass_intentions`, `transfers` |
| SimpleJWT | `authentication`, `messaging` (WebSocket), réglages | — |

Les modules gelés (ADR-006) gardent leur code et leurs migrations : supprimer `org` casse leurs modèles. Et le front actuel s'authentifie encore en SimpleJWT (`LEGACY_JWT_ENABLED`).

## 2. Décisions préalables (au porteur du projet)

1. **Sort des modules gelés** : les supprimer définitivement (code, tables, migrations écrasées) ou les réécrire sur `Node` avant la contraction. Recommandation : supprimer `donations`, `transfers`, `tv`, `spiritual`, `clergy_accounts`, `mass_intentions` du dépôt (l'historique Git les conserve), après un export de leurs tables.
2. **Bascule du front sur Keycloak** en production (`KEYCLOAK_ENABLED=true`, `LEGACY_JWT_ENABLED=false`) et migration effective des comptes (`migrate_users_to_keycloak --apply`).
3. **Fenêtre de maintenance** et sauvegarde restaurée avec succès juste avant.

## 3. Ordre proposé, une PR par étape

1. ~~Retirer les anciennes vues d'administration de `users` et leurs routes~~ : fait (ADR-015).
2. ~~Retirer le repli JWT historique~~ : fait (ADR-015).
3. Supprimer les apps gelées retenues (étape 1 des décisions).
4. Migrations « contract » : `users` (champs `role`, `pastoral_role`, `primary_parish`, `church`, `community`, `jwt_key` ; modèles `RoleAssignment`, `Membership`, `ClergySelfDeclaration`), `messaging` (`PriestProfile`), `news` et `agenda` (anciennes colonnes de portée `scope_parish`, `scope_diocese`, `scope_church`), `documents` (`parish_name`, `diocese`, statuts historiques), puis `org`.
5. Chaque migration : relue par `database-reviewer`, testée aller-retour sur une copie de la base de production.
