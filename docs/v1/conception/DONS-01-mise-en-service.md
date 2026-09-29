# DONS-01 — Mise en service : ce qui reste, qui le fait

> 27/09/2026. Suite de `DONS-00-cadrage.md`. Backend : PR #33 (`feat/v1-dons`). Front : branche `feat/v1-f-dons` (JanguBiUI). Maquettes web : canvas « Web · Ciel produit » (pages 13-14) ; mobile : canvas mobile (pages K, G08-G09, H01).

## 1. Ce qui est fait (vérifiable sans intervention)

| Brique | État | Vérification |
|---|---|---|
| App `donations` (modèles, services, API, tâches, admin en lecture) | fait | 995 tests, couverture dons 98 %, ruff et mypy propres, migrations aller-retour |
| Agrégateur factice (tests, CI, démonstration) | fait | notification signée HMAC, rejeu, doublons |
| Agrégateur PayDunya | fait, jamais appelé en réel | comparé au SDK officiel `paydunya` 1.0.7 (PyPI) : URLs `https://app.paydunya.com/{sandbox-api,api}/v1/`, en-têtes `PAYDUNYA-MASTER-KEY` / `PRIVATE-KEY` / `TOKEN`, `checkout-invoice/create` puis `checkout-invoice/confirm/{token}`, succès si `response_code == "00"`, statuts `pending` / `completed` / `cancelled` (+ `failed`, `expired` tolérés). La doc web (developers.paydunya.com) n'était pas joignable depuis l'environnement cloud : le format exact de l'IPN (`data[hash]` = SHA-512 de la clé maître) est à confirmer en sandbox, mais il ne sert que de déclencheur — le statut est toujours relu serveur à serveur. |
| Seed de démonstration (économe, économe diocésain, 3 fonds + quête impérée) | fait | `seed_demo`, `infra/keycloak/seed-demo-users.sh` |
| Maquettes web (12 écrans + 3 mis à jour, clair et sombre) et mobiles (17 écrans harmonisés) | publiées | canvas |
| Front web (feature `dons`, ADR-F12) | en cours sur `feat/v1-f-dons` | PR brouillon à venir |

## 2. Réglages par défaut (modifiables par variables d'environnement)

| Réglage | Défaut | Commentaire |
|---|---|---|
| `DONATIONS_PROVIDER` | `fake` | `production.py` retire le module dons si le fournisseur reste `fake` |
| `DONATIONS_MIN_AMOUNT` / `MAX_AMOUNT` | 100 / 1 000 000 FCFA | garde-fou ; le KYC reste chez l'agrégateur |
| `DONATIONS_FEE_RATE_BP` | 200 (2 %) | **à aligner sur le contrat PayDunya** (H3) : c'est le taux affiché au donateur |
| `DONATIONS_EXPIRE_HOURS` | 24 | un paiement non confirmé passe « Expiré » |
| `DONATIONS_DONOR_EMAIL_RETENTION_DAYS` | 90 | e-mail du donateur sans compte |
| `DONATIONS_RETURN_URL` | `http://localhost:3000/dons/retour` | le serveur ajoute `?don=<id>` (et `&annule=1` à l'annulation) ; en production : l'URL publique du front |
| `DONATIONS_CALLBACK_BASE_URL` | `http://localhost:8001` | doit être joignable **depuis Internet** par PayDunya (IPN) |
| `PAYDUNYA_MODE` | `test` | `live` seulement après recette sandbox |
| Préfixe des reçus | par paroisse (`SD`) | saisi à l'activation ; numéro `SD-2026-00147`, sans trou |

## 3. Ce qui dépend de toi (hors code)

1. **Compte PayDunya** : ouverture du compte marchand au nom de l'archidiocèse (H1), KYC, contrat (taux réel → `DONATIONS_FEE_RATE_BP`), clés sandbox puis live dans les secrets du serveur (`PAYDUNYA_*`). Demander à PayDunya s'il existe une API de relevé des reversements : sinon le rapprochement reste manuel (`list_payouts` renvoie une liste vide).
2. **Autorisation écrite de l'Ordinaire** (H4) : la décision réelle remplace la référence fictive `ARCH-DAK-2026-041` à l'activation de chaque paroisse (`PUT /platform/dons/activations/`).
3. **Serveur et Keycloak** : aucun environnement déployé pour l'instant. Il faut une URL publique HTTPS pour l'IPN et le retour navigateur, et les utilisateurs de démonstration Keycloak (`seed-demo-users.sh` : économe Anne Mendy, économe diocésain Bernard Coly).
4. **Origine du front** : renommer l'origine définitive (domaine) puis mettre à jour `DONATIONS_RETURN_URL`, les `redirect_uris` du client Keycloak `jangubi-web` et le CORS.
5. **Adresses de contact** : `aide@`, `paroisses@`, `donnees@` (réclamations sur les dons, exercice des droits loi 2008-12) à créer sur le domaine retenu.
6. **Recette locale et fusion** : `make act` vert (backend et front), recette sur la vraie pile (parcours sandbox PayDunya complet : don, retour, IPN, reçu, export), puis fusion des PR. Claude ne fusionne jamais.

## 4. Écarts connus, sans blocage

- **Nombre de dons d'une campagne** : la maquette affiche « 57 dons » sur la fiche publique ; `PublicFundDetail` n'expose pas ce compteur (seul `StaffFund.donations_count` le fait). À ajouter côté API si l'on veut l'afficher aux fidèles.
- **Budget ligne à ligne d'une campagne** : les maquettes montrent un budget détaillé ; l'API n'a qu'un texte `description`. Le front le rend ligne à ligne si le texte suit le format « libellé : montant ».
- **Répartition en ligne / espèces par dimanche** (graphique WEB-PAR-Dons) : `daily` ne donne qu'un total par jour. Ajouter `online` et `cash` à `SummaryDay` si le graphique à deux tons est voulu.
- **Statut du don au retour** (`DonationStatus`) : ni `payment_method` ni `net_amount`. La confirmation n'affiche donc pas « Wave » ni le montant affecté quand l'onglet n'a plus la réponse du checkout.
- **Écarts du rapprochement** (`ReconciliationIssue`) : `kind`, `reference`, `date` seulement ; ajouter le montant et le fonds rendrait la liste plus utile.
- **Création de fonds** (`FundCreateInput`) : pas de choix de destination (paroisse / curie) ; `StaffFund` renvoie `image_url` mais pas `image_id`.
- **Export** : pas d'option « inclure les noms » (les noms suivent la capacité `dons.voir_donateurs`) ni d'historique des exports (il est au journal d'audit).
- **Suivi d'une quête impérée** : le serveur ne liste que les paroisses où le fonds existe ; les paroisses « collecte non ouverte » des maquettes n'apparaissent pas.
- **Date du parcours fidèle** : les maquettes datent le don du 24 septembre sur la « Quête du dimanche 27 septembre », ouverte à partir du 26. Sans effet sur le code (le serveur refuse un fonds hors période) ; à corriger dans les maquettes si on les reprend.
