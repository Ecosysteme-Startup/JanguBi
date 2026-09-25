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
- **Modules gelés** : `donations`, `mass_intentions`, `transfers`, `spiritual`, `tv`, `rag`, `clergy_accounts`, `testing_examples`, plus des sous-parties de `bible`, `liturgy` et `rosary` (voir plan L0.4).

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
