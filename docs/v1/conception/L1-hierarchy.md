# L1 — Référentiel hiérarchique (`apps/hierarchy`)

> Conception du lot L1 (plan §2 L1 ; SRS §3.1, §5.1, §5.4 ; ADR-002). Version du 25/09/2026.

## 1. Modèles

| Modèle | Champs clés | Invariants |
|---|---|---|
| `NodeType` | `code` (unique), `label`, `is_territorial`, `holds_registers`, `order`, `allowed_parent_types` (M2M non symétrique) | Un type sans parent autorisé est un type **racine** (province, institut) |
| `Node` (`treebeard.MP_Node`) | `id` UUID, `type`, `name`, `code` (unique), `status` (`en_fondation`/`erige`/`supprime`), `address`, `city`, `lat`, `lng`, `erected_at`, `is_active_on_platform`, `located_in` (FK Node, lien géographique d'un nœud non territorial), `legacy_model`, `legacy_id` | Le parent doit être d'un type autorisé ; un type racine n'a pas de parent |
| `PlaceOfWorship` | `node`, `name`, `kind` (`eglise_paroissiale`, `succursale`, `chapelle`, `station`, `sanctuaire`), `is_main`, `address`, `city`, `lat`, `lng`, `is_active`, `legacy_id` | Au plus un lieu principal par nœud (contrainte partielle) |
| `MassSchedule` | `place`, `kind` (`messe`/`confession`/`adoration`), `weekday` (0 = lundi), `start_time`, `end_time`, `language`, `note`, `valid_from`, `valid_to` | `end_time > start_time`, `valid_to ≥ valid_from` |
| `ScheduleException` | `place`, `date`, `kind`, `cancelled`, `start_time`, `end_time`, `note` | Annulation sans heure = tout ce type ce jour-là ; sans `cancelled` = horaire supplémentaire (heure obligatoire) |

**Écarts assumés par rapport au SRS §5.1** : `holds_registers` (permet de dire qu'une quasi-paroisse reçoit des demandes d'actes comme une paroisse, sans coder de liste de types), `located_in` (une communauté religieuse est *située* dans un diocèse sans en dépendre, c. 586), et le type de lieu `succursale` (présent dans les données `org` actuelles, qu'on ne veut pas perdre).

## 2. Chemin matérialisé

`MP_Node` (pas de 4, alphabet base 36). Enfants, ancêtres et sous-arbre = une requête (`path__startswith`, `depth`). Pas d'`node_order_by` : le tri par nom est fait par les selectors. Le déplacement de nœud est hors périmètre V1 (on change le statut, on recrée).

## 3. Migrations

1. `0001_initial` : schéma.
2. `0002_seed_node_types` : catalogue des types « Sénégal » (réversible : supprime les types sans nœud).
3. `0003_migrate_org` : `org.Province/Diocese/Deanery/Parish/Church/ReligiousOrder/ReligiousCommunity` → `Node`/`PlaceOfWorship`, chemin matérialisé calculé à la main (les modèles historiques n'ont pas les méthodes treebeard). Chaque ligne garde `legacy_model` + `legacy_id`. Codes : ceux d'`org` quand ils existent (`DAK`, `DAKP`), sinon `<type>-<legacy_id>`. Réversible : supprime les nœuds hérités, leur sous-arbre et leurs lieux. `org` reste la source des apps non encore migrées jusqu'en L9.

Le doyen d'`org.Deanery.dean` sera converti en nomination `doyen` en L2.

## 4. Services, selectors

- `node_create`, `node_update` (y compris le statut), `place_create`, `place_update`, `schedule_replace` (remplace la semaine type d'un lieu), `schedule_exception_create`, `schedule_exception_delete`.
- `hierarchy_profile_load(profile="senegal")` : types + Province de Dakar, 7 diocèses, 5 doyennés de Dakar, Saint-Dominique et ses 2 lieux, horaires du pilote. Idempotent : un nœud existant est retrouvé par code **ou** par (parent, type, nom), ce qui évite les doublons avec les nœuds venus d'`org`.
- `nodes_import_csv` / `places_import_csv` : validation ligne à ligne ; tout s'exécute dans une transaction annulée si `dry_run` ou si une ligne est en erreur (simulation exacte, y compris les parents créés plus haut dans le fichier).
- `week.py` : calcul pur (sans base) des occurrences d'une semaine, exceptions comprises.

## 5. API (`/api/v1/`)

| Méthode | Chemin | Accès (L1) |
|---|---|---|
| GET | `hierarchy/node-types/` | public |
| GET/POST | `hierarchy/nodes/` (`?type=&parent=&q=&status=`) | lecture publique, écriture super-admin |
| GET/PATCH | `hierarchy/nodes/{id}/` | idem |
| GET | `hierarchy/nodes/{id}/children/`, `…/ancestors/` | public |
| GET/POST | `hierarchy/nodes/{id}/places/` | lecture publique, écriture super-admin |
| GET/PATCH | `hierarchy/places/{id}/` | idem |
| GET/PUT | `hierarchy/places/{id}/schedule/` | idem |
| GET/POST | `hierarchy/places/{id}/exceptions/`, DELETE `…/exceptions/{eid}/` | idem |
| POST | `hierarchy/import/nodes/?dry_run=`, `hierarchy/import/places/?dry_run=` | super-admin |
| GET | `public/nodes/` (annuaire : `q`, `city`, `diocese`, `type`, `on_platform`) | public, paginé |
| GET | `public/nodes/{id}/week/?start=` | public |

Écriture protégée par `IsSuperAdmin` avec `TODO(L2)` : remplacée par `HasCapability("structure.gerer" | "horaires.gerer")` au lot suivant.

**Format d'erreur V1** (SRS §7) : `{"error": {"code", "message", "details"}}`, appliqué par `V1ApiMixin` aux seules nouvelles APIs (les apps existantes gardent leur format jusqu'à leur adaptation, pour ne pas casser le front).

## 6. Tests

Invariants de parents, lieu principal unique, semaine avec exceptions (pur), import CSV (simulation, erreurs, parents créés dans le même fichier, atomicité), seed idempotent (deux passes, pas de doublon avec des nœuds `org` migrés), migration de données aller-retour sur une fixture `org` réaliste, APIs (public/anonyme, 403 non super-admin, 400 parent interdit, 404), EF-HIE-03 (`children`/`ancestors` en une requête).

## 7. Revue et retour arrière

- Index `hierarchy_node_path_pattern` (`varchar_pattern_ops`) : sans lui, `path__startswith` ne peut pas utiliser l'index unique sous une collation non `C` (migration 0004).
- **Retour arrière d'une release** : dé-appliquer d'abord les migrations `hierarchy` (`migrate hierarchy zero`, ou jusqu'à la migration de la release visée) **avant** de déployer l'ancienne image. Sinon les tables restent orphelines, sans dommage aujourd'hui, mais bloquantes dès qu'une autre app aura une clé étrangère vers `hierarchy.Node` (lot L2 : `users.BaseUser`).
- `migrate` doit être lancé par un seul processus (le calcul manuel des chemins de 0003 n'est pas protégé contre deux exécutions concurrentes).
