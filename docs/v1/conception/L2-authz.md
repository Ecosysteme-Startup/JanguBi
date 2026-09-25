# L2 — Personnes, offices, capacités (`apps/hierarchy`)

> Conception du lot L2 (plan §2 L2 ; SRS §3.2, §5.2, §5.4, §6 ; ADR-003). Version du 25/09/2026.

## 1. Modèles

| Modèle | Rôle |
|---|---|
| `Capability` (PK = code) | Catalogue **fermé** de 14 capacités (SRS §6.2), seedé par la migration 0006 |
| `OfficeType` | Office paramétrable : types de nœuds, ordre requis, cardinalité, `appointed_by` (offices nommeurs), `appointed_by_platform`, capacités, `inherits_down` |
| `OfficeAssignment` | Nomination datée : personne, office, nœud, `start_date`/`end_date`, statut `proposee → active → terminee` / `annulee`, nommé par, décret |
| `CapabilityOverride` | Retrait d'une capacité à un office dans le sous-arbre d'un diocèse |
| `AuditEvent` | Journal métier en insertion seule (`save` d'un existant et `delete` lèvent) |
| `BaseUser` (+) | `keycloak_sub`, `etat_de_vie`, `degre_ordre`, `incardination_node`, `institut_node`, `statut_verification`, `verification_note`, `verified_by/at`, `paroisse_suivie`, `consent_version/at` (expand : les anciens champs restent lisibles jusqu'en L9). `date_of_birth` reste sur `Profile` (pas de doublon). |

Écart : 16 offices au lieu de 15 — l'office `cure_in_solidum` (c. 517) matérialise l'exception à la cardinalité du curé citée par EF-PER-05.

## 2. Algorithme

```
grants(user) = [ (capacité, nœud, chemin, hérite, office) pour chaque nomination ACTIVE
                 dont start_date ≤ aujourd'hui ≤ end_date, capacités de l'office − retraits
                 du diocèse englobant ]
             + (si administrateur plateforme) PLATFORM_ADMIN_CAPABILITIES sur chemin "" (tout l'arbre)

peut(user, c, nœud)          = ∃ g ∈ grants, g.c = c ∧ (nœud.path = g.path ∨ (g.hérite ∧ nœud.path commence par g.path))
noeuds_autorises(user, c)    = Node.filter(OR des path__startswith / path=)
```

- **Cache** : `grants(user)` en cache Django (Redis en production), clé `authz:<date>:<version globale>:<version utilisateur>:<id>`. La date dans la clé fait tomber les nominations échues à minuit sans attendre la tâche. Les services invalident la version utilisateur (tout de suite et après commit) ; les retraits invalident la version globale. `peut()` sans requête une fois le cache chaud (test `assertNumQueries(0)`).
- **Plateforme** (Numerisen) : `structure.gerer`, `horaires.gerer`, `offices.nommer`, `personnes.verifier`, `tableau_bord.voir`, `actes.superviser`, `audit.voir`, `plateforme.admin` — **jamais** `actes.traiter`, `messagerie.*`, `confessions.*` (RG-09). Jusqu'à L3 : super-admin legacy ; ensuite, rôle de realm `platform_admin`.
- **Permission DRF** : `HasCapability("actes.traiter", node_resolver=...)` ; sans résolveur, la capacité sur au moins un nœud suffit et la vue filtre par `noeuds_autorises`.

## 3. Règles de nomination (EF-PER-04, -05)

Dans cet ordre : autorité (plateforme, ou `offices.nommer` sur le nœud **et** titulaire d'un office nommeur sur le nœud ou un ancêtre), compatibilité type d'office / type de nœud, condition d'ordre (rang du degré ≥ rang requis **et** statut clérical `verifie`), cardinalité (aucune nomination ouverte qui chevauche la période, verrou sur le nœud). Statut initial `active` si `start_date ≤ aujourd'hui`, sinon `proposee`. Tâche Beat quotidienne `assignments_sync_task` (00:15).

Mouvement annuel (CSV `action,email,office,node_code[,start_date,end_date,decree_ref]`, date d'effet) : pour un office à titulaire unique, le titulaire en place est terminé la veille (ligne en avertissement). Simulation exacte, application tout ou rien.

## 4. Vérification de l'état de vie (EF-PER-02, RG-07)

`POST /me/declaration/` : toujours `declare`, aucun effet sur les droits. `personnes.verifier` sur le nœud d'incardination (clerc) ou l'institut (consacré) ; à défaut de nœud, plateforme seulement. Pas d'auto-vérification.

## 5. Migration des droits existants (L2.9)

`manage.py migrate_legacy_rights --report plan.csv` produit la table de correspondance **sans écrire**. Après relecture humaine : `--apply`. Règles (SRS §5.4) : `diocese_admin` → `delegue_numerique_diocesain` ; `parish_admin` prêtre principal → `cure`, second prêtre → `vicaire_paroissial`, laïc → `referent_numerique` ; `church_admin` → vicaire ou secrétaire (**à valider à la main**) ; doyen d'`org.Deanery` → `doyen` ; `super_admin` / `province_admin` → manuel ; `pastoral_role` → `etat_de_vie` + `degre_ordre` (déclaré) ; appartenance principale → `paroisse_suivie`. Les nominations migrées contournent la condition d'ordre et portent une note « à revoir par la chancellerie ».

## 6. API

`GET /hierarchy/office-types/` · `GET/POST /hierarchy/assignments/` · `GET/PATCH /hierarchy/assignments/{id}/` (`terminer` | `annuler`) · `POST /hierarchy/assignments/import/?effective_date=&dry_run=` · `GET /hierarchy/verifications/` · `POST /hierarchy/verifications/{person_id}/decision/` · `GET/POST /hierarchy/capability-overrides/`, `DELETE …/{id}/` · `GET /me/capacites/` · `GET/POST /me/declaration/` · `GET /audit/`.

Les écritures de la structure (`/hierarchy/nodes`, lieux) passent sous `structure.gerer` ; horaires et exceptions sous `horaires.gerer` ; les imports vérifient la capacité ligne par ligne.

## 7. Remplacement des permissions des autres apps (L2.10)

Voir ADR-012 : `hierarchy` est converti dans ce lot ; `news`/`agenda` (L4), `documents` (L5), `messaging` (L6a) et `dashboards` (L8) le sont dans le lot qui bascule leur portée de `org.*` vers `Node`.
