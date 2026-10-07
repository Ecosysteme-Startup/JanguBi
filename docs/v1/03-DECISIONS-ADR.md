# Jàngu Bi — Registre des décisions d'architecture (ADR)

> Format court : contexte, décision, conséquences. Une décision « verrouillée » ne se rediscute pas sans nouvel ADR.
> Statuts possibles : **Verrouillée**, **À trancher**, **Remplacée**.

---

## ADR-001 — Refonte sur place, pas de réécriture
- **Statut** : Verrouillée (24/09/2026)
- **Contexte** : ~26 k lignes de code et ~22 k lignes de tests, architecture HackSoft saine, défauts concentrés dans l'identité, la hiérarchie et le périmètre.
- **Décision** : conserver le repo `JanguBi` et les apps saines. Refondre `org` / `users` / `authentication` ; geler le reste.
- **Conséquences** : migrations expand/contract ; tag `pre-v1` ; les anciens champs restent lisibles jusqu'en L9.

## ADR-002 — Hiérarchie : arbre générique paramétrable
- **Statut** : Verrouillée
- **Décision** : `NodeType` + `Node` (django-treebeard `MP_Node`), lieux de culte séparés de l'arbre. Arbre de la vie consacrée dans le même modèle, avec des types non territoriaux.
- **Pourquoi** : un diocèse ajoute zones, secteurs ou aumôneries sans code. Au Sénégal, une seule province, et les structures varient d'un diocèse à l'autre.
- **Alternatives écartées** : tables typées (existant, rigide) ; `ltree` natif (moins d'outillage Django).

## ADR-003 — Autorisation : offices et capacités, héritage sur le sous-arbre
- **Statut** : Verrouillée
- **Décision** : toute autorisation passe par `peut(user, capacite, node)`. Les capacités sont un catalogue fermé. Les offices sont paramétrables. Les nominations sont datées.
- **Pourquoi** : c'est le fonctionnement réel de l'Église (l'office confère le pouvoir sur un territoire). Cela supprime les 5 mécanismes superposés (`UserRole`, `pastoral_role`, `RoleAssignment`, `Membership`, déclarations).
- **Conséquences** : `IsAnyAdmin` et consorts sont interdits dans les apps V1 ; tests de matrice obligatoires.

## ADR-004 — Authentification : Keycloak, hiérarchie dans l'application
- **Statut** : Verrouillée
- **Décision** : Keycloak 26 (OIDC, PKCE côté web, jetons vérifiés par JWKS). Trois rôles de realm seulement : `fidele`, `staff`, `platform_admin`. MFA TOTP pour `staff` et `platform_admin`. La hiérarchie, les offices et les capacités restent dans l'application.
- **Pourquoi** : on délègue la sécurité des comptes (MFA, reset, sessions, brute force) sans dupliquer un référentiel ecclésial vivant (plus de 170 paroisses, mutations annuelles) dans des groupes Keycloak.
- **Conséquences** : SimpleJWT, `drf-jwt`, `jwt_key` et l'OTP maison sont retirés. Les comptes sont migrés avec import des hachages `pbkdf2_sha256`. Keycloak devient un service à sauvegarder.

## ADR-005 — Messagerie temps réel conservée, chiffrement de bout en bout visé
- **Statut** : Verrouillée pour la messagerie ; **À trancher** pour la technologie E2E (étude L6b)
- **Décision** : WebSocket via Django Channels (channel layer Redis). E2E étudié entre `vodozemac` (Olm/Megolm, WASM) et OpenMLS ; le serveur reste un annuaire de clés et un relais opaque.
- **Garde-fou** : point d'arrêt si l'étude dépasse 12 jours. Dans ce cas, pilote en Fernet côté serveur avec une mention de transparence.
- **Règle métier liée** : pas de confession par message (Saint-Siège, 2002 et 2020). La messagerie sert à l'écoute et à l'accompagnement ; les rendez-vous de confession se prennent en présentiel.

## ADR-006 — Gel des modules hors V1 par configuration
- **Statut** : Verrouillée
- **Décision** : réglage `JANGUBI_MODULES` (liste des modules actifs). `apps/api/urls.py` n'inclut que les modules actifs, et les tâches Beat des modules gelés sont retirées. Le code et les migrations restent.
- **Modules gelés** : des sous-parties de `bible`, `liturgy` et `rosary` (voir plan L0.4). Les modules entiers hors V1 ont été supprimés (ADR-016).

## ADR-007 — Broker Celery : RabbitMQ conservé
- **Statut** : Verrouillée (révisable après le pilote)
- **Contexte** : Redis suffirait au volume du pilote, mais RabbitMQ est déjà en place et fonctionne.
- **Décision** : garder RabbitMQ comme broker Celery. Redis sert au cache, au channel layer Channels et au cache JWKS.
- **Conséquence** : aucun changement d'infrastructure dans la V1.

## ADR-008 — Contenus liturgiques et droits
- **Statut** : Verrouillée
- **Décision** : Bible en **Crampon 1923** (domaine public ; statut à confirmer avant la mise en ligne publique). Lectures du jour selon `LITURGY_SOURCE` : `aelf` seulement avec un accord écrit de l'AELF, sinon `crampon_refs`. Calendrier liturgique calculé localement.
- **Pourquoi** : les CGU de l'AELF interdisent toute redistribution sans autorisation expresse.

## ADR-009 — Actes : suivi de démarche, jamais de délivrance numérique
- **Statut** : Verrouillée
- **Décision** : l'application suit la demande jusqu'au retrait de l'original signé et scellé. Pas de PDF d'acte, pas de coffre-fort. La paroisse destinataire est toujours celle du sacrement.

## ADR-010 — CI locale obligatoire avec `act`
- **Statut** : Verrouillée
- **Décision** : aucun push sur `develop`, `stage` ou `main` sans `make act` vert (ruff, mypy, pytest dans le conteneur du runner). Hook `pre-push` fourni. Les jobs qui publient (Docker push, déploiement) ne sont **jamais** lancés via `act`.
- **Pourquoi** : économiser les minutes GitHub Actions et ne jamais déclencher un déploiement cassé (le job `trigger-deploy` suit automatiquement un push vert).

## ADR-011 — Données sensibles et conformité (loi 2008-12)
- **Statut** : Verrouillée
- **Décision** : consentement explicite horodaté, minimisation, conservation limitée (messages 180 j, pièces 90 j après clôture), aucun contenu de message accessible à un administrateur, tableaux de bord agrégés au-dessus de la paroisse, journal d'audit immuable.
- **À faire (L9)** : registre des traitements et déclaration à la CDP ; réévaluation de l'hébergement avant l'ouverture publique.

## ADR-012 — Remplacement des permissions app par app, au lot qui migre la portée
- **Statut** : Verrouillée (25/09/2026, lot L2)
- **Contexte** : le plan L2.10 prévoit de remplacer `IsAnyAdmin` et les contrôles ad hoc de `news`, `agenda`, `documents` et `messaging` dès L2. Or ces apps portent encore leur portée sur `org.Parish` / `org.Church` ; les lots L4, L5 et L6a remplacent ces clés par des `Node`. Faire la conversion en L2 obligerait à écrire un pont `org → Node` puis à le réécrire deux lots plus tard.
- **Décision** : L2 livre le moteur (`peut`, `noeuds_autorises`, `HasCapability`) et convertit `hierarchy`. Chaque autre app bascule sur les capacités dans le lot qui migre sa portée : `news` et `agenda` en L4, `documents` en L5, `messaging` en L6a, `dashboards` en L8. D'ici là, l'ancien modèle (`RoleAssignment`) continue d'autoriser ces apps ; aucun nouveau code ne s'en sert.
- **Conséquences** : le critère de sortie « plus aucune app V1 n'utilise `IsAnyAdmin` » est atteint à la fin de L6a (L8 pour les tableaux de bord), pas à la fin de L2. Un test par lot vérifie qu'aucune vue de l'app convertie n'importe plus `IsAnyAdmin`.

## ADR-013 — Contrat d'API V1 : les routes historiques d'une app sont remplacées au lot de l'app
- **Statut** : Verrouillée (25/09/2026, lot L4)
- **Contexte** : les apps V1 (`news`, `agenda`, `documents`, `messaging`) exposent des routes bâties sur `org.*` et sur les rôles (`parish/<id>/`, `diocese/<id>/`, `admin/…`, `my-parish/`). Le SRS §7 fixe un nouveau contrat (`/news/?node=`, `/staff/news/`, `/me/feed/`…). Garder les deux doublerait le code et les tests, et l'ancien contrat ne peut pas être autorisé par les capacités sans un pont `org → Node` jetable.
- **Décision** : au lot qui adapte une app, ses routes historiques sont **retirées** et remplacées par celles du SRS §7 ; les tests des routes retirées partent avec elles. Les données restent (expand) : les anciennes colonnes de portée sont conservées jusqu'en L9. Le contrat de référence est `schema.yml`, régénéré à chaque lot. Chaque rapport de lot liste les routes retirées et ajoutées.
- **Conséquences** : le front V1 (Auth.js + capacités) consomme le nouveau contrat ; l'ancien front ne doit pas être redéployé sur un backend V1. La mise en production passe par `stage` (recette) avec le front V1 (plan : `stage` à la fin de L3, L6a, L9).

## ADR-014 — Chiffrement de bout en bout : technologie et calendrier
- **Statut** : **Proposée, à trancher par le porteur du projet** (25/09/2026, étude L6b, point d'arrêt du plan)
- **Contexte** : ADR-005 laisse ouvert le choix entre `vodozemac` (Olm/Megolm) et OpenMLS. L'étude (`docs/v1/conception/L6b-e2e-etude.md`) chiffre l'E2E complet (serveur, front, preuve de concept) à 13 à 18 jours, au-delà du seuil de 12 jours.
- **Proposition** : technologie `vodozemac` via `matrix-sdk-crypto-wasm` (chemin web éprouvé, multi-appareils et sauvegarde de clés natifs, adapté au 1:1), le serveur exposant le sous-ensemble d'API de clés attendu par `OlmMachine`. Calendrier : **report après le pilote** ; pilote en Fernet côté serveur, accès applicatif au contenu fermé (L6a), mention de transparence dans la politique de confidentialité, clé Fernet hors base avec rotation documentée (L9).
- **Conséquences** : aucun code E2E dans la V1 du pilote. Les endpoints `/e2e/*` du SRS §7 restent réservés. Si la décision est de livrer avant le pilote, on commence par la preuve de concept à deux navigateurs et on s'arrête si elle échoue.

## ADR-015 — Keycloak seule authentification, sans période de transition
- **Statut** : Verrouillée (25/09/2026, décision du porteur du projet)
- **Contexte** : ADR-004 prévoyait une transition où SimpleJWT restait accepté (`LEGACY_JWT_ENABLED`) le temps de migrer le front. L'application n'a jamais été en production : il n'y a ni comptes ni sessions à préserver.
- **Décision** : Keycloak est la seule authentification de l'API et du WebSocket. Retirés : SimpleJWT (et `token_blacklist`), `jwt_key`, les routes `auth/` et `users/` (inscription, activation, mot de passe, changement d'e-mail, anciennes vues d'administration, rôles, adhésions, déclaration de clergé historique), l'authentification par session des API, le jeton dans l'URL du WebSocket (tickets seulement), le repli « super-administrateur » par `is_superuser`. `/me/` est au format V1 (GET, PATCH, DELETE).
- **Conséquences** : le front V1 doit passer par Auth.js (Keycloak) et par les tickets WebSocket. Les modèles de l'ancien modèle de rôles (`RoleAssignment`, `Membership`, `org.*`) restent tant que les modules gelés en dépendent (voir `conception/L9-contraction.md`).

## ADR-016 — Contraction : suppression de l'ancien modèle et des modules hors V1
- **Statut** : Verrouillée (25/09/2026, décision du porteur du projet)
- **Contexte** : l'application n'a jamais été en production ; aucune donnée n'est à préserver. Les modules gelés (ADR-006) et l'ancien modèle de rôles bloquaient la contraction prévue en L9.
- **Décision** : suppression des apps `org`, `donations`, `mass_intentions`, `transfers`, `spiritual`, `tv`, `rag`, `clergy_accounts`, `errors`, `testing_examples`, `custom_admin`, de la messagerie inter-clergé et de `PriestProfile` ; suppression de `RoleAssignment`, `Membership`, `ClergySelfDeclaration`, `SecurityAuditLog`, des champs `role`, `pastoral_role`, `onboarding_state`, `clergy_validation_status`, `diocese`, `province`, `religious_community`, `is_admin`, `Profile.primary_parish`, des anciennes portées de `news` et `agenda`, de `target_parish`, `parish_name`, `diocese` et des statuts historiques des demandes d'actes. **Historique des migrations remis à zéro** (une migration initiale par app, plus les extensions `vector` et `pg_trgm` et les catalogues de types de nœuds, capacités et offices).
- **Conséquences** : toute base existante (développement, staging) doit être **recréée** (`make down -v` puis `make up`, `make init-all`, `make seed-demo`). Les sous-modules gelés restants lisent l'état de vie V1 (`apps.hierarchy.persons`). ADR-006 ne concerne plus que ces sous-modules.

## ADR-017 — Dons et quêtes : réintégration, sans que Numerisen touche l'argent
- **Statut** : Verrouillée (27/09/2026, décision du porteur du projet ; hypothèses H1 à H4 validées)
- **Contexte** : les dons étaient hors V1 (« pas d'argent dans la V1 ») et l'app `donations` a été supprimée par l'ADR-016. L'étude du 27/09/2026 (`docs/design/dons-quetes-etude.md`) conclut que la collecte est faisable à trois conditions : Numerisen ne touche jamais l'argent, l'Église autorise la collecte par écrit, le paiement se fait hors de l'app sur iPhone.
- **Décision** :
  - nouvelle app `apps/donations` (module `donations` de `JANGUBI_MODULES`), bâtie sur l'arbre, les offices et `peut()` ; la collecte exige en plus l'**activation du nœud** (`DonationActivation`, avec la référence de l'autorisation écrite de l'Ordinaire, c. 1265) ;
  - **H1** : l'archidiocèse (économat) est titulaire du compte marchand chez un **agrégateur agréé BCEAO** (instruction 001-01-2024), avec une clé d'affectation par paroisse ; les reversements sont rattachés au diocèse ;
  - l'agrégateur est derrière une interface `PaymentProvider` (`create_checkout`, `verify_callback`, `fetch_status`, `list_payouts`) : `FakeProvider` pour les tests et la démonstration, `PayDunyaProvider` à valider contre le contrat ; la production refuse l'agrégateur factice (le module est alors retiré) ;
  - un don n'est **confirmé que par le serveur** : notification signée **et** statut relu chez l'agrégateur, ou réconciliation périodique ; le retour du navigateur n'a aucun effet ;
  - **H2** : fonds de type quête dominicale, quête impérée (destination curie, c. 1266), campagne, contribution annuelle ; chaque don est attaché à un fonds et n'en change jamais (c. 1267 §3) ; **aucune offrande de messe** (c. 945-958) ;
  - **H3** : frais affichés, couverts au choix du donateur (décoché par défaut), sinon déduits ; aucune commission Numerisen ;
  - **iOS et Android** : aucun paiement dans l'app ; l'app ouvre la page web publique de don dans le navigateur externe (guidelines Apple 3.2.1 vi et 3.2.2 iv) ;
  - **c. 848** : aucune dépendance entre `donations` et `documents`, `messaging`, `confessions` (test d'imports) ;
  - **loi 2008-12** : don anonyme possible, aucun classement ni liste publique, noms visibles du seul curé et de l'économe paroissial (`dons.voir_donateurs`), agrégats au-dessus de la paroisse, payloads chiffrés, aucune donnée de don dans les logs, adresse des dons sans compte effacée après 90 jours ; reçu **simple**, jamais fiscal.
- **Conséquences** : six capacités ajoutées au catalogue fermé et un office `econome_paroissial` (migration `hierarchy.0009`) ; SRS §1.3, §6, §7 et §8.4 amendés ; côté front, dégel de la feature `dons` par un ADR front après validation des maquettes. Détail : `docs/v1/conception/DONS-00-cadrage.md`.

## ADR-018 — Aucune IA : recherche et recommandations en plein texte PostgreSQL
- **Statut** : Verrouillée (30/09/2026, décision du porteur du projet)
- **Contexte** : la recherche des versets, « Pour vous » (Parole) et les voisins « contenu » de la sonothèque reposaient sur des embeddings (modèle local `fastembed`/ONNX, 768 dimensions, pgvector + HNSW). En recette, le calcul des vecteurs de la Bible (35 283 versets) a dépassé 3, 4 puis 6 Go de mémoire sans aboutir (six passes, toutes tuées par le noyau), alors que le worker tient en 512 Mo au repos. Mesures : `onnxruntime` 62 Mo dans l'image, index HNSW des versets 79 Mo et colonne 59 Mo en base. Aucun usage n'exige une IA : la recherche servie était déjà lexicale (le mode hybride n'était demandé par aucun client), et le porteur n'envisage aucun cas d'usage d'IA.
- **Décision** :
  - **aucun modèle d'IA ni d'embeddings** dans la plateforme : `fastembed` retiré, ainsi que `EmbeddingService`, `compute_embeddings_task`, `seed_embeddings`, `check_embeddings` et les réglages `EMBEDDING_*`, `PGVECTOR_ENABLED`, `FASTEMBED_*`, `GEMINI_*`, `RAG_GENERATION_ENABLED` ;
  - **recherche des versets** : plein texte PostgreSQL en configuration `fr_unaccent` (français, sans accents, racinisé ; `PG_TS_CONFIG`) avec `websearch_to_tsquery`, score 0,6 × `ts_rank` + 0,4 × similarité trigramme, repli trigramme `%` (index GIN) pour les fautes de frappe. Le paramètre `hybrid` reste accepté, sans effet ;
  - **« Pour vous » (Parole)** : proximité lexicale pondérée par la rareté des mots (TF-IDF) calculée en SQL sur `tsv` ; mêmes signaux, bonus, exclusions, diversité et charge utile qu'avant ;
  - **voisins « contenu » (audio)** : score SQL sur les métadonnées (album, temps liturgique, mots-clés, source, compositeur, interprètes, titre) ;
  - **schéma en deux temps** (retour arrière possible) : les index HNSW sont supprimés et les colonnes `embedding` vidées et retirées du modèle (`bible.0005`, `audio.0005`, `rosary.0005`) ; colonnes supprimées à la livraison suivante (`bible.0006`, `audio.0006`, `rosary.0006`, 01/10/2026), migrations réversibles. Les mots vides sont filtrés avant le retrait des accents (dictionnaire `fr_mots_vides`, `audio.0006`). L'extension `vector` et le paquet `pgvector` restent : les migrations initiales les importent.
- **Conséquences** : plus de pic de mémoire au calcul nocturne ; le worker de recette revient à 512 Mo ; image allégée d'`onnxruntime` et de ses dépendances ; « Pour vous » est calculé partout, poste local et CI compris, sans téléchargement. La recherche par le *sens* (« j'ai peur de demain ») n'est pas couverte : elle trouve les mots, pas les concepts ; toute réintroduction d'une IA demande un nouvel ADR.
