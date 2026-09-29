# Jàngu Bi — Plan backend V1, de A à Z

> Version du 24/09/2026. Référentiels : `02-SRS-BACKEND-V1.md` (quoi), `03-DECISIONS-ADR.md` (pourquoi), `04-CI-LOCALE-ET-GIT.md` (comment livrer).

---

## 0. En une page

**Stratégie : refondre sur place, pas réécrire.** Le code existant compte environ 26 000 lignes et à peu près autant de lignes de tests. La couche HackSoft est saine, et les briques documents, messagerie, liturgie et bible fonctionnent. Les problèmes se concentrent dans le **modèle d'identité et de hiérarchie** et dans le **périmètre** : c'est là qu'on concentre l'effort.

**10 lots, environ 11 à 13 semaines pour un développeur assisté de Claude Code**, dans un ordre imposé par les dépendances :

| Lot | Contenu | Dépend de | Estimation |
|---|---|---|---|
| **L0** | Préparation : hygiène git, baseline verte, gel des modules hors V1, CI locale, docs | — | 3 à 4 j |
| **L1** | Référentiel hiérarchique : arbre `Node`/`NodeType`, lieux de culte, horaires, import CSV, profil « Sénégal » | L0 | 6 à 8 j |
| **L2** | Personnes, offices, nominations, capacités, moteur `peut()`, audit | L1 | 7 à 9 j |
| **L3** | Keycloak : OIDC, JWKS, Channels, provisioning, MFA staff, migration des comptes | L2 | 6 à 8 j |
| **L4** | Ma paroisse : annonces (dimanche), horaires publics, agenda, notifications | L2, L3 | 5 à 6 j |
| **L5** | Demandes d'actes : adaptation du workflow (paroisse du sacrement, retrait, file par nœud) | L2, L3 | 5 à 6 j |
| **L6a** | Parler à un prêtre : messagerie adaptée, rendez-vous de confession | L2, L3 | 6 à 7 j |
| **L6b** | Chiffrement de bout en bout : étude (spike) puis implémentation serveur | L6a | 8 à 12 j |
| **L7** | La Parole : Bible Crampon, lectures du jour, chapelet personnel | L0 | 4 à 5 j |
| **L8** | Tableaux de bord par nœud | L2 à L6a | 3 à 4 j |
| **L9** | Conformité, sécurité, exploitation, préparation du pilote | tous | 5 à 6 j |

**Parallélisable** : L7 peut démarrer dès L0 terminé. L4, L5 et L6a sont indépendants entre eux une fois L3 livré.

**Livraison** : chaque lot passe par une ou plusieurs branches `feat/v1-lX-…` puis une PR vers `develop`, **après `make act` vert**. `stage` est mis à jour à la fin des lots L3, L6a et L9. `main` n'est mis à jour qu'après la recette du pilote.

---

## 1. Principes d'exécution

1. **Refonte sur place, migrations « expand → migrate → contract ».** On ajoute les nouvelles structures, on migre les données, on bascule le code, puis on supprime l'ancien dans un lot ultérieur. Aucune migration destructive dans le même lot que la bascule.
2. **TDD systématique.** L'ordre est : tests (agent `django-tdd-assistant`), implémentation, revue (`django-reviewer`). Toute migration passe par `database-reviewer` avant et après.
3. **HackSoft strict** : `models`, `services` (écritures, `@transaction.atomic`), `selectors` (lectures), `serializers`, `apis` (HTTP seulement), `permissions`. Pas de logique dans les modèles ni dans les vues.
4. **Toute autorisation passe par le moteur de capacités** (`peut(user, capacite, noeud)`), sauf les droits de base du fidèle. Aucun nouveau `if user.role == …` n'est accepté.
5. **Gel plutôt que suppression** des modules hors V1 : le code reste, mais les routes, les tâches Beat et la navigation sont désactivées par configuration (`JANGUBI_MODULES`).
6. **CI locale obligatoire** : `make act` (ruff + mypy + pytest) doit être vert avant tout push vers `develop`, `stage` ou `main`. Voir `04-CI-LOCALE-ET-GIT.md`.
7. **Chaque endpoint est documenté** (`@extend_schema`). Le schéma OpenAPI est régénéré à la fin de chaque lot et sert de contrat au frontend.

---

## 2. Les lots en détail

### L0 — Préparation (3 à 4 j)

| # | Tâche | Livrable | Critère de sortie |
|---|---|---|---|
| L0.1 | Hygiène git : fusionner `fix/audit-beta` (15 commits d'avance) dans `develop`, réaligner `stage` et `main` (divergences constatées), archiver les branches mortes (tag `archive/<nom>` puis suppression locale) | `develop` à jour, liste des branches archivées | `git branch` ne liste que les branches vivantes |
| L0.2 | Baseline des tests : faire passer au vert les échecs connus (`docs/backlog/BUG-TESTS-001`, `-002`) ou les marquer `xfail` avec un ticket | Rapport de baseline | `make act` vert sur `develop` |
| L0.3 | Tag de sécurité `pre-v1` sur `develop` | Tag | Poussé |
| L0.4 | **Gel des modules hors V1** : réglage `JANGUBI_MODULES` (liste des modules actifs) ; `apps/api/urls.py` n'inclut que les modules actifs ; les tâches Beat des modules gelés sont retirées ; test qui vérifie qu'une route gelée renvoie 404 | Réglage + tests | Voir la liste ci-dessous |
| L0.5 | Documentation : copier ce kit dans `docs/v1/`, mettre à jour `CLAUDE.md` (racine et `JanguBi/`), archiver `../memory/*.md` et les anciens SRS dans `docs/archive/` | Docs | Relu |
| L0.6 | Vérifier le gate CI local : `make act` fonctionne, `.secrets.example` est présent, `.actrc` est versionné | CI locale | Un run `act` complet documenté |

**Modules gelés (ADR-006)** : `donations`, `mass_intentions`, `transfers`, `spiritual`, `tv`, `rag`, `clergy_accounts` (remplacé en L2), `testing_examples`, ainsi que les parties « Lectio / Plans de lecture / HomilieNote » de `bible`, « Offices des Heures » de `liturgy` et « Chapelet communautaire » de `rosary`.

### L1 — Référentiel hiérarchique (6 à 8 j)

Nouvelle app **`apps/hierarchy/`**. `apps/org/` est conservée pendant la transition, puis contractée en L9.

| # | Tâche | Détail |
|---|---|---|
| L1.1 | Modèles `NodeType`, `Node` | `django-treebeard` (`MP_Node`, chemin matérialisé). `NodeType` porte : `code`, `label`, `allowed_parent_types` (M2M), `is_territorial`, `order`. `Node` porte : `type`, `name`, `code` unique, `status` (`en_fondation`, `erige`, `supprime`), `address`, `city`, `lat`, `lng`, `erected_at`. |
| L1.2 | `PlaceOfWorship` et `MassSchedule` | Lieu de culte (église paroissiale, chapelle, station, sanctuaire) rattaché à un `Node`. Horaires récurrents (jour, heure, type : messe, confession, adoration ; langue ; note) et exceptions datées. |
| L1.3 | Validation structurelle | Un nœud ne peut avoir qu'un parent d'un type autorisé. Un seul lieu de culte « principal » par paroisse. Tests de ces invariants. |
| L1.4 | Profil « Sénégal » | Fixture/commande `seed_hierarchy_profile senegal` : les types de nœuds et leurs parents autorisés, puis la Province de Dakar, les 7 diocèses, les 5 doyennés de Dakar et la paroisse pilote Saint-Dominique avec ses 2 lieux de culte. |
| L1.5 | Import CSV | Commande et endpoint d'import pour les nœuds et les lieux de culte : validation ligne à ligne, mode simulation (`dry_run`), rapport d'erreurs. |
| L1.6 | Migration des données | `org.Province/Diocese/Deanery/Parish/Church` vers `Node`/`PlaceOfWorship`. Chaque `Node` garde `legacy_model` et `legacy_id` pour la traçabilité. Migration réversible. |
| L1.7 | API structure | `GET /api/v1/hierarchy/nodes/` (arbre, filtres par type et par parent), `GET …/nodes/{id}/`, `GET …/nodes/{id}/children/`, `POST/PATCH` (capacité `structure.gerer`), `GET/POST …/places/`, `GET/PUT …/places/{id}/schedule/`, et l'annuaire public en lecture seule. |

**Sortie** : l'arbre complet du Sénégal est chargé, la migration de `org` passe dans les deux sens et les tests sont verts.

### L2 — Personnes, offices, capacités (7 à 9 j)

| # | Tâche | Détail |
|---|---|---|
| L2.1 | Extension de `BaseUser` (ou modèle `Person` 1-1) | `etat_de_vie` (laïc, clerc, consacré), `degre_ordre`, `incardination_node` (FK Node, diocèse), `institut` (FK Node de l'arbre de la vie consacrée), `statut_verification` (déclaré, vérifié, rejeté), `paroisse_suivie` (FK Node), `keycloak_sub` (unique, nullable jusqu'en L3). |
| L2.2 | Catalogue `Capability` | Liste fermée, codée en seed et versionnée (voir SRS §6). Pas de création de capacité à la volée. |
| L2.3 | `OfficeType` | `code`, `label`, `node_types` (M2M), `required_order` (aucun, diacre, prêtre, évêque), `cardinality` (`one`, `many`), `appointed_by` (M2M OfficeType), `capabilities` (M2M), `inherits_down` (booléen), `is_system`. |
| L2.4 | `OfficeAssignment` | `person`, `office_type`, `node`, `start_date`, `end_date`, `status` (proposée, active, terminée, annulée), `appointed_by` (Person), `decree_ref`, `decree_file` (File). Contraintes : cardinalité, condition d'ordre, compatibilité type d'office / type de nœud. |
| L2.5 | `CapabilityOverride` par diocèse | Un diocèse peut retirer une capacité à un office dans son sous-arbre (jamais en ajouter une au-delà du catalogue). |
| L2.6 | **Moteur `peut()`** | `apps/hierarchy/authz.py` : `peut(user, capacite, node) -> bool` et `noeuds_autorises(user, capacite) -> QuerySet[Node]`. L'héritage passe par le chemin matérialisé. Cache par utilisateur (Redis, clé versionnée, invalidée à chaque changement de nomination). Permission DRF générique `HasCapability("actes.traiter", node_from="kwargs.node_id")`. |
| L2.7 | Services de nomination | Nommer, terminer, annuler, avec les contrôles de l'autorité qui nomme (`appointed_by`). Mouvement annuel : import CSV avec date d'effet, simulation, application atomique. Tâche Beat quotidienne qui active ou termine les nominations selon leurs dates. |
| L2.8 | Journal d'audit métier | `AuditEvent` immuable : acteur, action, cible, nœud, métadonnées, IP. Écrit par les services, jamais par les vues. |
| L2.9 | Migration des droits existants | `UserRole`, `pastoral_role` et `RoleAssignment` convertis en nominations (table de correspondance dans le SRS §5.4). `Membership` principale convertie en `paroisse_suivie`. Les anciens champs restent en lecture jusqu'en L9. |
| L2.10 | Remplacement des permissions | `IsAnyAdmin`, `IsSuperAdmin` et les contrôles ad hoc des apps V1 sont remplacés par `HasCapability`, app par app, avec des tests d'autorisation par capacité. |
| L2.11 | API | `/hierarchy/office-types/`, `/hierarchy/assignments/` (CRUD selon capacité), `/hierarchy/assignments/import/`, `/me/capacites/` (liste `[{capacite, node_id, herite}]` pour le front), `/hierarchy/people/{id}/verification/`. |

**Sortie** : le curé pilote est nommé et nomme sa secrétaire. `peut()` est couvert par des tests de matrice (office × capacité × position dans l'arbre), et plus aucune app V1 n'utilise `IsAnyAdmin`.

### L3 — Keycloak (6 à 8 j)

| # | Tâche | Détail |
|---|---|---|
| L3.1 | Service Keycloak | Keycloak 26 dans `docker-compose.yml` (base Postgres dédiée), realm `jangubi` versionné en JSON (`infra/keycloak/realm-jangubi.json`) : clients `jangubi-web` (public, PKCE) et `jangubi-api` (bearer-only). Rôles de realm : `fidele`, `staff`, `platform_admin`. Politique MFA TOTP exigée pour `staff`. Thème de connexion Jàngu Bi (étape front). |
| L3.2 | Authentification DRF | `apps/authentication/keycloak.py` : classe `KeycloakJWTAuthentication` (PyJWT + JWKS mis en cache dans Redis, vérification de `iss`, `aud`, `exp`, `azp`). Provisioning à la première requête (`keycloak_sub` → Person). |
| L3.3 | Authentification WebSocket | Middleware Channels qui valide le même jeton au handshake, ferme avec 4401 si le jeton est expiré, et contrôle l'origine avec `OriginValidator` et une liste explicite. |
| L3.4 | Synchronisation des rôles | À chaque nomination active, ajout du rôle `staff` via l'API admin Keycloak (compte de service). Retrait quand plus aucune nomination n'est active. `platform_admin` est géré à la main. |
| L3.5 | Migration des comptes | Export des `BaseUser` vers Keycloak avec import des hachages `pbkdf2_sha256` (format compatible Keycloak), ce qui évite toute réinitialisation de mot de passe. Script idempotent, avec mode simulation. |
| L3.6 | Retrait de l'ancienne authentification | SimpleJWT, `drf-jwt`, `jwt_key`, les endpoints `/api/auth/*` et l'OTP maison sont retirés du chemin actif. Les endpoints de profil restent, sous `/api/v1/me/`. |
| L3.7 | Tests | Jetons signés par une clé de test (fixture JWKS locale), sans Keycloak réel en CI. Test d'intégration optionnel (`-m keycloak`) contre le conteneur. |

**Sortie** : connexion OIDC de bout en bout en local, WebSocket authentifié, comptes migrés en simulation, CI verte sans Keycloak.

### L4 — Ma paroisse (5 à 6 j)

- `news` : les types sont réduits à `annonce` et `article` (`lettre_pastorale` est gelée). Champs `is_sunday_notice` et `sunday_date`. La portée est un `Node` (paroisse ou lieu de culte), plus un scope global Numerisen. Publication sous la capacité `annonces.publier`, programmation (`publish_at`), désignation « annonce du dimanche », compteur de lectures.
- Horaires publics : `GET /public/places/{id}/schedule/` et `GET /public/nodes/{id}/week/` (messes et confessions de la semaine, exceptions comprises).
- `agenda` : les événements sont rattachés à un `Node`, avec inscription, capacité maximale et liste des inscrits (`evenements.gerer`).
- Notifications : nouvelle annonce de la paroisse suivie, rappel d'événement. Canaux in-app et e-mail, avec silence de 22 h à 6 h.
- Flux fidèle : `GET /me/feed/` (paroisse suivie et global).

### L5 — Demandes d'actes (5 à 6 j)

- Statuts V1 : `soumise → en_verification → (complement_demande ↔ en_verification) → prete_a_retirer → retiree`, avec la branche `rejetee`. `document_deposited` devient `prete_a_retirer`. La logique « coffre-fort » est gelée.
- `target_parish` devient une FK vers un `Node`, via une migration depuis `org.Parish`.
- La file appartient au nœud et non à une personne. Accès sous `actes.traiter` sur la paroisse du sacrement, ou `actes.superviser` en agrégé.
- Retrait : lieu, horaires, mode (au secrétariat de la paroisse du sacrement, ou transmission à la paroisse suivie).
- Registre : champs de recherche (volume, page, numéro d'acte, mentions marginales). Notes internes jamais exposées au fidèle.
- Conservation : les pièces justificatives sont purgées 90 jours après `retiree` ou `rejetee` (tâche Beat).
- SLA et relances conservées, seuils paramétrables par nœud.

### L6a — Parler à un prêtre (6 à 7 j)

- `messaging` : la joignabilité passe par la capacité `messagerie.recevoir_fideles` sur la paroisse suivie (et les aumôneries), avec des disponibilités (plages, absent jusqu'au).
- Correctifs de l'audit : CGU par utilisateur (A1), WebSocket (A2), socket de notifications global et payload enrichi (A3).
- Flag `confession_notice` renvoyé par l'API pour le bandeau. Aucun endpoint d'administration ne lit le contenu des messages, et un test le vérifie.
- Mineurs : `date_of_birth` obligatoire pour ouvrir une conversation, refus sous 18 ans (V1).
- Nouvelle app **`apps/confessions/`** :
  - `ConfessionSlotRule` : règles récurrentes par prêtre et par lieu (jour, heure de début, heure de fin, durée du créneau, période de validité).
  - `ConfessionSlot` : créneaux générés sur 4 semaines glissantes.
  - `ConfessionBooking` : réservation (statuts `reservee`, `annulee_fidele`, `annulee_pretre`, `honoree`, `absent`).
  - Aucun champ de contenu : ni motif, ni texte libre.
  - Rappels à J-1 et H-2. Annulation par le prêtre avec un message aux réservants.
  - Vue prêtre : réservations nominatives. Vue secrétariat : initiales seulement.

### L6b — Chiffrement de bout en bout (8 à 12 j, dont 3 j d'étude)

- **Étude (3 j)** : comparer `vodozemac` (Olm/Megolm, compilé en WASM, utilisé par Element) et OpenMLS. Critères : maturité web, gestion multi-appareils, sauvegarde des clés, coût d'intégration. Livrable : un ADR et une preuve de concept à deux navigateurs.
- **Rôle du serveur** (quel que soit le choix) : annuaire des appareils et de leurs clés publiques, distribution des clés à usage unique, relais de messages chiffrés opaques, sauvegarde chiffrée de la clé de récupération (le serveur ne peut pas la lire), rotation lors d'un changement de prêtre.
- Coexistence : les conversations créées avant la bascule restent en Fernet, en lecture seule, avec une mention.
- **Point d'arrêt** : si l'étude conclut à un coût supérieur à 12 jours, le chiffrement de bout en bout passe après le pilote, avec une mention de transparence dans la politique de confidentialité. La décision revient à toi.

### L7 — La Parole (4 à 5 j)

- Bible : import de la **Crampon 1923** (Wikisource, domaine public, statut à confirmer) via l'ETL, qui remplace le texte AELF en base. Mention de la traduction dans l'API.
- Lectures du jour : **option A** si l'AELF donne son accord écrit (flux actuel conservé, zone corrigée) ; sinon **option B** : références du jour et texte Crampon. L'option est pilotée par le réglage `LITURGY_SOURCE`.
- Calendrier liturgique (temps, fête, couleur) : calcul local, sans dépendance à l'AELF.
- Chapelet personnel : mystères du jour et prières traditionnelles. Audit de la provenance des textes de méditation.

### L8 — Tableaux de bord (3 à 4 j)

- `GET /api/v1/dashboards/nodes/{id}/` sous la capacité `tableau_bord.voir`, avec des indicateurs agrégés sur le sous-arbre : fidèles rattachés et actifs, annonces publiées et lues, demandes (volume, délai médian, retards), messagerie (conversations, délai de première réponse, **jamais de contenu**), réservations de confession.
- Au-dessus du niveau paroisse, aucune donnée nominative. Cache de 5 minutes.
- Tableau de bord plateforme (`plateforme.admin`) : comptes, part du staff avec MFA, santé des files, dernières exécutions Beat.

### L9 — Conformité, sécurité, exploitation (5 à 6 j)

- Consentement explicite horodaté (version des CGU), export des données du fidèle (JSON), suppression du compte avec anonymisation des traces nécessaires.
- Registre des traitements et dossier de déclaration à la CDP : document produit en L9, dépôt fait par toi.
- Revue de sécurité (skill `django-security`, agent dédié) : rate limiting, en-têtes, CORS, secrets, droits sur les fichiers.
- Contraction des migrations : suppression de `org.*`, `RoleAssignment`, `pastoral_role`, `UserRole`, `Membership`, SimpleJWT (migrations « contract »).
- Observabilité : Sentry, logs structurés, Uptime Kuma, sauvegardes Postgres testées (restauration).
- Seed du pilote, recette sur `stage`, PR `stage → main`.

---

## 3. Calendrier indicatif (1 développeur + Claude Code)

| Semaine | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Lots | L0 | L1 | L1-L2 | L2 | L3 | L3 · L7 | L4 | L5 | L6a | L6b | L6b · L8 | L9 | Recette |

Avec deux développeurs : L4, L5 et L6a en parallèle, soit environ 9 semaines.

---

## 4. Définition de « terminé » (chaque lot)

- [ ] Tests écrits avant le code. Couverture des services et des selectors du lot ≥ 90 %.
- [ ] `ruff`, `mypy` et `pytest` verts **via `make act`**. Pas de `# type: ignore` nouveau sans justification.
- [ ] Revue `django-reviewer`, plus `database-reviewer` s'il y a des migrations.
- [ ] Migrations réversibles, testées dans les deux sens sur une copie de la base.
- [ ] Endpoints documentés (`@extend_schema`), `schema.yml` régénéré et commité.
- [ ] Aucune logique d'autorisation hors du moteur de capacités.
- [ ] `CLAUDE.md` et `docs/v1/` mis à jour si une décision a changé.
- [ ] PR vers `develop` avec description, captures OpenAPI et liste des migrations.

## 5. Risques et parades

| Risque | Parade |
|---|---|
| Migration de l'identité (L2, L3) qui casse l'existant | Expand/contract, lecture des anciens champs jusqu'en L9, tag `pre-v1`, test de migration aller-retour |
| Keycloak plus lourd que prévu à exploiter | Realm versionné, compte de service minimal, doc d'exploitation, sauvegarde de la base Keycloak |
| E2E trop coûteux | Point d'arrêt après l'étude (L6b) |
| AELF refuse | Option B déjà prévue (L7) |
| Baseline de tests rouge | L0.2 bloque tout le reste |
| Minutes GitHub Actions consommées par des pushs ratés | `make act` obligatoire (voir le document 04) et hook `pre-push` |
