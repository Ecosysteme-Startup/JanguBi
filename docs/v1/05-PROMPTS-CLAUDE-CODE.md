# Jàngu Bi — Prompts Claude Code (backend V1)

> Un prompt par lot, à coller dans Claude Code lancé depuis `JanguBi/`. Chaque prompt suppose que `CLAUDE.md` est chargé.
> Règle commune : **Claude Code s'arrête et demande validation** aux points marqués ⏸.

---

## Prompt 0 — Amorçage de session (à coller au début de chaque session)

```
Contexte : backend Jàngu Bi, refonte V1. Lis dans l'ordre :
docs/v1/00-LIRE-D-ABORD.md, docs/v1/01-PLAN-BACKEND-V1.md, docs/v1/03-DECISIONS-ADR.md,
docs/v1/04-CI-LOCALE-ET-GIT.md, puis la section du SRS (docs/v1/02-SRS-BACKEND-V1.md) utile au lot en cours.

Règles non négociables :
- HackSoft strict (models/services/selectors/serializers/apis/permissions), keyword-only, ApplicationError.
- Toute autorisation passe par le moteur de capacités (apps/hierarchy/authz.py), jamais par un rôle codé en dur.
- TDD : tests d'abord (agent django-tdd-assistant), puis code, puis revue (django-reviewer ; database-reviewer si migration).
- Migrations expand/contract, réversibles, testées aller-retour.
- Aucun push vers develop/stage/main sans `make act` vert. Tu travailles sur une branche feat/v1-lX-… et tu ouvres une PR ; tu ne merges pas toi-même.
- Tu ne lances jamais livraison-recette.yml via act.
- Tu mets à jour docs/v1 et CLAUDE.md si une décision change, et tu proposes un ADR plutôt que de trancher seul.

Résume en 10 lignes ce que tu as compris du lot <LX>, liste les fichiers que tu vas toucher, puis attends mon « go ».
```

---

## L0 — Préparation

```
Lot L0 (docs/v1/01-PLAN-BACKEND-V1.md §2 L0). Objectifs :
1. Hygiène git : état de develop, stage, main et fix/audit-beta (15 commits d'avance sur develop). Propose le plan de fusion
   (fix/audit-beta → develop via PR ; réalignement stage/main) et la liste des branches à archiver (tag archive/<nom>). ⏸ avant toute action git.
2. Baseline : lance `make act` sur develop. Liste les échecs, rattache-les à docs/backlog/BUG-TESTS-00x. Corrige ceux qui sont triviaux ;
   marque les autres xfail(strict=True) avec un ticket. Objectif : make act vert.
3. Gel des modules (ADR-006) : ajoute le réglage JANGUBI_MODULES (config/django/base.py, liste par défaut = modules V1),
   rends conditionnels les include() de apps/api/urls.py et les entrées CELERY_BEAT_SCHEDULE, et écris les tests
   (route gelée → 404, tâche gelée absente du schedule). Ne supprime aucun code ni aucune migration.
4. CI : ajoute .actrc, .secrets.example, scripts/git-hooks/pre-push, la cible `make hooks`, et les modifications de
   django.yml (paths-ignore, PR brouillon) décrites dans docs/v1/04-CI-LOCALE-ET-GIT.md §6.
5. Docs : docs/SRS_* et docs/JanguBi_SRS_* → docs/archive/ (git mv). Vérifie que CLAUDE.md pointe vers docs/v1.
6. Pose le tag pre-v1 sur develop après le merge. ⏸ avant de pousser le tag.
Livrables : PR « chore(v1): préparation L0 » + rapport de baseline dans docs/v1/rapports/L0-baseline.md.
```

---

## L1 — Référentiel hiérarchique

```
Lot L1 (plan §2 L1, SRS §3.1, §5.1, §5.4, ADR-002).
Étape 1 — Architecture : agent code-architect. Produis docs/v1/conception/L1-hierarchy.md : modèles (treebeard MP_Node),
invariants, index, stratégie de migration org→hierarchy (legacy_model/legacy_id, réversible), endpoints, plan de tests. ⏸
Étape 2 — Tests d'abord (django-tdd-assistant) : invariants de parents autorisés, un seul lieu principal par paroisse,
semaine des horaires avec exceptions, import CSV (dry_run), commande seed_hierarchy_profile senegal idempotente,
migration de données aller-retour sur une fixture org réaliste.
Étape 3 — Implémentation : nouvelle app apps/hierarchy (NodeType, Node, PlaceOfWorship, MassSchedule, ScheduleException),
services, selectors, APIs du SRS §7 « Hiérarchie » et « Lieux et horaires ». Écriture protégée TEMPORAIREMENT par IsSuperAdmin
avec un TODO(L2) : le moteur de capacités arrive au lot suivant.
Étape 4 — Seed « Sénégal » : types (province, diocese, zone, doyenne, paroisse, quasi_paroisse, aumonerie, ceb, mouvement,
institut, province_religieuse, communaute), Province de Dakar, 7 diocèses, doyennés de Dakar (Plateau-Médina, Grand Dakar-Yoff,
Niayes, Sine, Petite-Côte), paroisse Saint-Dominique avec l'église Saint-Dominique et la chapelle de la Cité universitaire,
horaires du pilote (brief : dim 7h30, 9h30, 11h30, 18h30 ; semaine 7h, 18h30 ; sam confessions 16h-18h).
Étape 5 — Revue django-reviewer + database-reviewer, `make act`, schema.yml, PR(s) : feat/v1-l1-models, feat/v1-l1-migration-org, feat/v1-l1-api.
```

---

## L2 — Personnes, offices, capacités

```
Lot L2 (plan §2 L2, SRS §3.2, §5.2, §5.4, §6, ADR-003). C'est le cœur de la V1 : sois exhaustif sur les tests.
Étape 1 — code-architect : docs/v1/conception/L2-authz.md. Détaille l'algorithme de peut() et de noeuds_autorises()
(requêtes sur le chemin matérialisé), la stratégie de cache (clé par utilisateur versionnée, invalidation), la permission
DRF HasCapability(capacite, node_resolver), et le plan de migration des droits existants (table SRS §5.4). ⏸
Étape 2 — Tests (django-tdd-assistant) : la matrice SRS §6.4 en entier + cardinalité, condition d'ordre, appointed_by,
activation/terminaison par dates (freezegun), CapabilityOverride limité au diocèse, import du mouvement annuel (dry_run,
avertissements, erreurs, application atomique), AuditEvent écrit par chaque service.
Étape 3 — Implémentation dans apps/hierarchy : Capability (seed fermé), OfficeType (seed §6.3), OfficeAssignment,
CapabilityOverride, AuditEvent, authz.py, services de nomination, tâche Beat quotidienne, APIs SRS §7 « Offices »,
« Personnes », GET /me/capacites/.
Étape 4 — Extension de BaseUser (SRS §5.2) avec migration expand. Data migration des droits existants vers les nominations :
produis d'abord un rapport CSV de correspondance (qui devient quoi) SANS écrire. ⏸ je valide le rapport avant l'écriture.
Étape 5 — Remplace IsAnyAdmin/IsSuperAdmin et les contrôles ad hoc par HasCapability dans les apps V1
(hierarchy, news, agenda, documents, messaging), app par app, une PR par app, avec tests d'autorisation.
Étape 6 — django-auth-implementer + django-reviewer + database-reviewer, make act, PR.
```

---

## L3 — Keycloak

```
Lot L3 (plan §2 L3, SRS §3.3, ADR-004).
Étape 1 — code-architect : docs/v1/conception/L3-keycloak.md (realm, clients, rôles, politique MFA, flux PKCE côté front,
validation JWKS côté API, WebSocket, synchronisation staff, migration des comptes, plan de retrait de SimpleJWT). ⏸
Étape 2 — Infra locale : service keycloak (26.x) + base Postgres dédiée dans docker-compose.yml ; realm versionné
infra/keycloak/realm-jangubi.json (clients jangubi-web public PKCE, jangubi-api bearer-only ; rôles fidele/staff/platform_admin ;
MFA TOTP requise pour staff et platform_admin ; thème provisoire) ; import automatique au démarrage ; cibles make kc-up / kc-export.
Étape 3 — Tests d'abord : fixture JWKS locale (clé RSA de test) ; jeton valide, expiré, mauvais iss/aud ; provisioning idempotent
par sub ; WebSocket 4401 ; endpoints staff refusés sans amr/acr MFA.
Étape 4 — Implémentation : apps/authentication/keycloak.py (KeycloakJWTAuthentication, cache JWKS Redis), middleware Channels,
service de synchronisation du rôle staff (compte de service, tâche Celery déclenchée par les nominations),
script manage.py migrate_users_to_keycloak --dry-run (import des hachages pbkdf2_sha256).
Étape 5 — Bascule : DEFAULT_AUTHENTICATION_CLASSES → Keycloak ; retrait des routes /api/auth/* du chemin actif, de SimpleJWT,
drf-jwt, jwt_key (migration expand : champ gardé jusqu'en L9). ⏸ avant la bascule.
Étape 6 — Revue django-auth-implementer + skill django-security, make act (sans Keycloak réel), PR ; mise à jour de CLAUDE.md
(section Authentification).
```

---

## L4 — Ma paroisse

```
Lot L4 (plan §2 L4, SRS §3.5).
Adapte apps/news et apps/agenda au modèle Node + capacités : types annonce/article (lettre_pastorale gelée), is_sunday_notice +
sunday_date, publish_at avec tâche de publication, compteur de lectures (une par personne), portée = Node, flux /me/feed/.
Horaires publics : /public/nodes/{id}/week/ (depuis L1). Agenda : événements par Node, inscription avec capacité et 409 si complet,
export CSV. Notifications : nouvelle annonce de la paroisse suivie, rappel d'événement, silence 22h-6h, préférences.
Migrations expand/contract depuis les champs de portée actuels. TDD, django-reviewer, make act, PR.
```

---

## L5 — Demandes d'actes

```
Lot L5 (plan §2 L5, SRS §3.6, §8.1, ADR-009).
1. code-architect : table de migration des statuts (document_deposited → prete_a_retirer, ajout retiree, annulee),
   target_parish → FK Node, suppression fonctionnelle du coffre-fort (gel, pas de suppression de données). ⏸
2. Tests : cycle §8.1 complet (transitions permises et interdites), cloisonnement par actes.traiter, notes internes invisibles
   du fidèle, références du registre, annulation par le fidèle, SLA par nœud, purge à 90 jours, vue agrégée actes.superviser.
3. Implémentation + migrations + notifications bilatérales (e-mail via le modèle Email + on_commit).
4. Revue, make act, PR.
```

---

## L6a — Parler à un prêtre et rendez-vous de confession

```
Lot L6a (plan §2 L6a, SRS §3.7, §8.3, ADR-005, RG-08/09/13).
Messagerie : joignabilité via messagerie.recevoir_fideles + disponibilités ; correctifs A1 (CGU par utilisateur), A2 (WebSocket :
origines explicites, refresh), A3 (socket /ws/notifications/ global, payload enrichi, recherche serveur) ; refus < 18 ans ;
confession_notice dans les réponses ; test qui prouve qu'aucun endpoint admin ne renvoie de contenu.
Nouvelle app apps/confessions : ConfessionSlotRule, ConfessionSlot (génération sur 4 semaines glissantes, tâche Beat),
ConfessionBooking (AUCUN champ de contenu), réservation avec verrou (select_for_update) et 409 si pris, annulations,
rappels J-1 et H-2, planning prêtre nominatif et planning secrétariat avec initiales.
TDD, django-reviewer, make act, PR (une pour messaging, une pour confessions).
```

---

## L6b — Chiffrement de bout en bout

```
Lot L6b (plan §2 L6b, ADR-005).
Étape 1 — Étude, 3 jours maximum : compare vodozemac (Olm/Megolm, WASM) et OpenMLS. Critères : maturité navigateur,
multi-appareils, sauvegarde et récupération des clés, changement de prêtre, coût d'intégration front et back, licences.
Livrables : ADR-012 et une preuve de concept (deux navigateurs, un message chiffré relayé par le serveur). ⏸ je décide
(go, ou report après le pilote si l'estimation dépasse 12 jours).
Étape 2 (si go) — Serveur : annuaire des appareils et des clés publiques, clés à usage unique (claim atomique), relais de charges
utiles opaques, sauvegarde chiffrée de la clé de récupération, rotation au changement de titulaire, coexistence avec les conversations
Fernet existantes (lecture seule). Aucun clair stocké, aucun log de contenu. TDD, revue sécurité, make act, PR.
```

---

## L7 — La Parole

```
Lot L7 (plan §2 L7, SRS §3.4, ADR-008).
1. ETL : import de la Bible Crampon 1923 (source Wikisource ; commande idempotente, contrôle du nombre de livres, chapitres
   et versets, mention de la traduction). ⏸ si le statut de domaine public de l'édition est douteux, je tranche.
2. Calendrier liturgique local (temps, fêtes principales, couleur) avec tests sur des dates connues (Pâques 2026 = 5 avril,
   24/09/2026 = jeudi de la 25e semaine du temps ordinaire, couleur verte).
3. LITURGY_SOURCE = aelf | crampon_refs ; en crampon_refs, les lectures du jour = références + texte Crampon.
4. Chapelet personnel : mystères selon le jour, prières traditionnelles ; liste des textes dont la provenance est à vérifier.
TDD, revue, make act, PR.
```

---

## L8 — Tableaux de bord

```
Lot L8 (plan §2 L8, SRS §3.8, RG-11).
GET /dashboards/nodes/{id}/ (tableau_bord.voir), indicateurs agrégés sur le sous-arbre, AUCUNE donnée nominative au-dessus de la
paroisse et AUCUN contenu de message (tests dédiés), cache 5 min. GET /dashboards/platform/ (plateforme.admin) : comptes, part MFA,
santé Celery et Beat. Requêtes optimisées (pas de N+1 : assertNumQueries). TDD, revue, make act, PR.
```

---

## L9 — Conformité, sécurité, exploitation

```
Lot L9 (plan §2 L9, SRS §3.9, §9, ADR-011).
1. Consentement versionné, export JSON, suppression avec anonymisation ; tests.
2. docs/v1/conformite/registre-des-traitements.md (finalités, bases légales, catégories, durées, destinataires, transferts, mesures).
3. Revue de sécurité complète (skill django-security) : rate limiting, en-têtes, CORS, fichiers, secrets, dépendances.
4. Migrations « contract » : suppression de org.*, RoleAssignment, UserRole, pastoral_role, Membership, SimpleJWT, jwt_key. ⏸ avant chaque suppression.
5. Exploitation : sauvegarde et restauration testées (Postgres app + Keycloak), Sentry, logs, Uptime Kuma, seed du pilote.
6. make act, PR develop → stage, recette, puis PR stage → main avec tag v1.0.0. ⏸ à chaque étape.
```
