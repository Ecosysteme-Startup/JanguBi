# Jàngu Bi — Prompts Claude Code : module Dons et quêtes

> Copie transmise le 27/09/2026. Les écarts entre ces prompts et l'état du dépôt sont traités dans
> `docs/v1/conception/DONS-00-cadrage.md` (§2 et §7).

Prérequis dans le dépôt (commit + push avant de lancer une session cloud) :

- `docs/design/jangubi-kit-maquettes/` (kit de reprise : briefs, gabarits, scripts) ;
- `docs/design/dons-quetes-etude.md` (copie du doc projet `claude/dons-quetes-etude.md`).

Les trois prompts partent des mêmes hypothèses par défaut, à confirmer au premier point d'arrêt ⏸ :

- **H1** Titulaire du compte marchand : l'archidiocèse (économat diocésain), un sous-compte ou une clé d'affectation par paroisse. Numerisen ne détient jamais les fonds.
- **H2** Types en V1 : quête dominicale, quêtes impérées (reversées à la curie), campagnes de projet, contribution annuelle. Offrandes de messe EXCLUES (relèvent des intentions de messe).
- **H3** Frais : affichés au donateur, qui choisit de les couvrir (case pré-décochée) ; sinon déduits du don. Pas de commission Numerisen sur les dons.
- **H4** Autorisation écrite de l'archevêché : supposée obtenue pour le pilote Saint-Dominique ; mention visible sur les pages de don.

## Prompt 1 — Maquettes web (canvas « Jàngu Bi — Web · Ciel produit »)

```
Contexte : Jàngu Bi (Numerisen), plateforme des fidèles catholiques du Sénégal. On ajoute le module Dons et quêtes
aux maquettes web existantes, sans toucher au style.

Lis d'abord, en entier : docs/design/jangubi-kit-maquettes/README-REPRISE.md, briefs/BRIEF-V1.md (§2, §5, §6),
briefs/BRIEF-WEB-CIEL.md, briefs/ECRANS-WEB.md, gabarits/tpl-web-public.dc.html et tpl-web-app.dc.html,
puis docs/design/dons-quetes-etude.md. Lis sur le canvas (Artifact read, url https://claude.ai/artifact/NMrbMhcbbFaTXXojoXg8Az)
project/canvas.json et ces écrans de référence : WEB-FID-Accueil, WEB-FID-Demande-Nouvelle, WEB-FID-Ma-Paroisse,
WEB-PAR-Tableau-de-bord, WEB-PAR-Demandes, WEB-DIO-Tableau-de-bord, WEB-Design-System.

Hypothèses H1 à H4 (voir en tête de docs/design/PROMPTS-DONS.md). ⏸ Résume-les en 5 lignes et attends mon « go »
ou mes corrections avant de dessiner.

Règles non négociables :
- Église : chaque don est rattaché à un fonds et ne sert qu'à lui (c. 1267 §3) ; la quête impérée est décidée par
  l'Ordinaire et reversée à la curie (c. 1266) ; AUCUN appel au don dans le parcours d'une demande d'acte, de
  confession ou de messagerie, aucun service conditionné à un paiement (c. 848) ; pas d'offrande de messe ici.
- Paiement : Numerisen ne détient jamais l'argent ; le paiement se fait sur la page de l'agrégateur agréé BCEAO
  (Wave, Orange Money, Free Money, carte) ; on montre la redirection et le retour, jamais un faux formulaire de carte.
- Données : le don révèle la religion et des finances (loi 2008-12) : don anonyme possible, aucun classement ni
  liste publique de donateurs, noms visibles seulement par l'économe et le curé, agrégats au-dessus de la paroisse.
- Style : tokens Ciel exacts, Libre Franklin pour l'interface, Source Serif pour la Parole seulement, aucun des tics
  « IA » listés dans BRIEF-WEB-CIEL §1 (pas de jauge-thermomètre géante, pas de stat cards, pas de dégradé).
- Montants en FCFA, espaces insécables (« 5 000 FCFA »), montants suggérés sobres (1 000 / 2 000 / 5 000 / 10 000
  + montant libre), jamais de culpabilisation dans la micro-copie.

Écrans à produire (largeur 1440, même chrome que les écrans existants, entrée de menu « Dons » ajoutée à la barre
latérale fidèle et paroisse) :
Fidèle
- WEB-FID-Donner : choisir le fonds (quête du dimanche 27 sept., quête impérée pour le Grand Séminaire de Brin,
  campagne « Toiture de la chapelle de la Cité universitaire », contribution annuelle), montant, don anonyme,
  couverture des frais, récapitulatif collant à droite, mention de l'autorisation diocésaine.
- WEB-FID-Don-Redirection : écran de transition vers la page sécurisée de l'agrégateur (ce qui va se passer,
  moyens acceptés, retour automatique).
- WEB-FID-Don-Confirmation : succès (référence, fonds, montant, reçu disponible) + variante « paiement en attente de
  confirmation » en encadré.
- WEB-FID-Mes-Dons : historique, filtres par fonds et par année, reçu téléchargeable (reçu simple, pas un reçu
  fiscal tant que le statut n'est pas confirmé), total de l'année visible par le seul fidèle.
- WEB-FID-Campagne : page d'une campagne (objectif, montant réuni en barre sobre, usage des fonds, mises à jour du
  curé, bouton Donner).
Public
- WEB-Don-Paroisse : page web publique de don d'une paroisse (celle qu'ouvre l'iPhone hors de l'app), sans compte
  obligatoire, même contenu que WEB-FID-Donner en plus compact.
Paroisse (capacité dons.gerer, économe et curé)
- WEB-PAR-Dons : vue des fonds (collecté ce mois, par fonds, par moyen, en ligne vs espèces), dernières opérations
  (noms masqués sauf capacité dons.voir_donateurs), reversements de l'agrégateur, un seul graphique.
- WEB-PAR-Campagne-Editeur : créer une campagne (titre, objectif, dates, usage des fonds, visuel, publication),
  aperçu à droite.
- WEB-PAR-Quete-Saisie : saisie de la quête en espèces d'une messe (date, messe, fonds, montant compté, deux
  compteurs, observation), historique des saisies.
- WEB-PAR-Dons-Export : rapprochement et export comptable (période, fonds, CSV / Excel, écarts signalés).
Diocèse et plateforme
- WEB-DIO-Quetes-Imperees : définir une quête impérée (objet, date, paroisses concernées) et suivre les reversements
  par paroisse (agrégats).
- WEB-PLA-Paiements : santé de l'intégration (agrégateur, webhooks reçus / en échec, rapprochement, incidents).
Mets à jour WEB-Design-System (badges de statut de paiement : initié, en attente, confirmé, échoué, remboursé) et
WEB-FID-Ma-Paroisse / WEB-Fiche-Paroisse (bloc sobre « Soutenir la paroisse »).

Méthode :
1. Écris d'abord docs/design/ECRANS-DONS-WEB.md (écran, contenu, états, liens). ⏸ Attends mon « go ».
2. Lance des sous-agents en parallèle (fidèle+public / paroisse / diocèse+plateforme+DS), chacun lit les écrans
   de référence avant d'écrire, un fichier .dc.html par écran, format du BRIEF-V1 §6.
3. Contrôles automatiques (support.js, DCLogic, $preview = racine, hex hors tokens, liens morts), captures
   (scripts/shot.py) et revue visuelle de chaque écran ; corrige.
4. Variantes sombres avec scripts/build_dark.py, puis publication sur le canvas existant : ajoute les écrans,
   une page « Dons et quêtes — clair » et « — sombre », mets à jour Main.dc.html (sommaire) ; ne republie que les
   fichiers ajoutés ou modifiés, relis canvas.json juste avant de l'envoyer.
Réponse finale : liste des écrans (ID | taille | titre) et points à valider.
```

## Prompt 2 — Maquettes mobile React Native (canvas « Jàngu Bi — App mobile · Ciel »)

```
Contexte : Jàngu Bi, app React Native (Expo Router, react-native-reusables, NativeWind, Lucide), iOS et Android.
On ajoute le module Dons et quêtes aux maquettes mobiles existantes, sans changer le style.

Lis d'abord, en entier : docs/design/jangubi-kit-maquettes/README-REPRISE.md, briefs/BRIEF-V1.md (§2, §5, §6),
briefs/BRIEF-MOBILE.md, briefs/ECRANS.md, gabarits/tpl-ios.dc.html, docs/design/dons-quetes-etude.md. Sur le canvas
(Artifact read, url https://claude.ai/artifact/78YJ3YiLtjZWCb82hBsYjG) lis project/canvas.json et les écrans
APP-B01-Accueil, APP-C01-Paroisse, APP-D03-Nouvelle-Type, APP-D06-Nouvelle-Recap, APP-D07-Demande-Envoyee,
APP-G01-Staff-Accueil, APP-H01-Design-System, AND-H02-Accueil. Charge aussi le skill vercel-react-native-skills.

Hypothèses H1 à H4 (docs/design/PROMPTS-DONS.md). ⏸ Résume-les et attends mon « go ».

Contrainte stores (décisive, à respecter à la lettre) :
- iOS : le don dans l'app est réservé aux organisations approuvées par Apple AVEC Apple Pay (guideline 3.2.1 vi),
  indisponible au Sénégal. Donc sur iPhone : aucun formulaire de montant ni de paiement dans l'app. L'app présente
  les fonds et les campagnes, puis un bouton « Donner sur le site » qui ouvre la page web de la paroisse dans
  Safari (SFSafariViewController interdit : Safari externe, guideline 3.2.2 iv). Montre la feuille d'information
  avant l'ouverture et le retour dans l'app (lien universel) avec l'état du don.
- Android : même parcours web par prudence (éligibilité « dons défiscalisés » non établie), écran AND équivalent.
Règles Église, données et style : identiques au prompt web (c. 1267 §3, c. 1266, c. 848, pas d'offrande de messe,
anonymat possible, aucun classement, FCFA, pas de culpabilisation, tokens Ciel, rien d'« IA »).

Écrans (390×844, hauteur ajustée ; Android 412×915) :
- APP-K01-Soutenir : entrée depuis l'onglet Paroisse (« Soutenir Saint-Dominique ») : fonds ouverts (quête du
  dimanche, quête impérée Grand Séminaire de Brin, campagne toiture de la chapelle, contribution annuelle),
  mention de l'autorisation diocésaine, aucun montant.
- APP-K02-Campagne : détail d'une campagne (objectif, avancement sobre, usage des fonds, nouvelles du curé).
- APP-K03-Vers-Le-Site : bottom sheet « Vous allez donner sur le site sécurisé de Jàngu Bi » (moyens acceptés :
  Wave, Orange Money, Free Money, carte ; retour automatique ; rien n'est payé dans l'app).
- APP-K04-Page-Web-Don : la page web mobile ouverte dans Safari (barre d'adresse Safari réelle, fonds, montants
  suggérés + libre, anonymat, frais, bouton Continuer vers le paiement).
- APP-K05-Retour-Confirme : retour dans l'app après paiement confirmé (référence, fonds, montant, reçu).
- APP-K06-Retour-En-Attente : paiement en attente de confirmation de l'opérateur (explication, pas de doublon).
- APP-K07-Mes-Dons : historique personnel (profil > Mes dons), filtres par année, reçus.
- APP-G08-Staff-Quete : saisie de la quête en espèces après une messe (messe, fonds, montant, deux compteurs).
- APP-G09-Staff-Fonds : vue des fonds pour l'économe (agrégats, dernières opérations, noms masqués par défaut).
- AND-K01-Soutenir et AND-K04-Page-Web-Don : équivalents Material 3 (Chrome Custom Tab interdit, navigateur externe).
Mets à jour APP-H01-Design-System (statuts de paiement) et APP-C01-Paroisse (bloc « Soutenir la paroisse »).

Méthode : 1) docs/design/ECRANS-DONS-MOBILE.md ⏸ ; 2) sous-agents en parallèle (fidèle iOS / staff + Android + DS),
lecture des écrans de référence obligatoire ; 3) contrôles automatiques, captures, revue et corrections ;
4) build_dark.py puis publication sur le canvas existant (pages « Dons — clair / sombre », sommaire mis à jour,
seuls les fichiers nouveaux ou modifiés, canvas.json relu juste avant l'envoi).
Réponse finale : liste des écrans et points à valider.
```

## Prompt 3 — Backend Django (dépôt JanguBi)

```
Contexte : backend Jàngu Bi (Django 5.2, DRF, Celery/RabbitMQ, Redis, PostgreSQL), refonte V1. On réactive et on
refond le module gelé `donations` pour les dons et quêtes. Lis d'abord : CLAUDE.md, docs/v1/00-LIRE-D-ABORD.md,
docs/v1/02-SRS-BACKEND-V1.md (capacités §6, API §7, cycles de vie §8), docs/v1/03-DECISIONS-ADR.md,
docs/v1/04-CI-LOCALE-ET-GIT.md, docs/design/dons-quetes-etude.md, puis tout le code de apps/donations
(modèles DonationCampaign, Donation, services, vues, tests) et de apps/mass_intentions.

Étape 0 — Cadrage ⏸
Écris docs/v1/conception/DONS-00-cadrage.md : état de l'existant (ce qui se garde, ce qui se refait), hypothèses
H1 à H4 (docs/design/PROMPTS-DONS.md), ADR-012 « Dons et quêtes » (Numerisen ne détient jamais les fonds ;
agrégateur agréé BCEAO derrière une interface PaymentProvider ; paiement hors app sur iOS ; pas d'offrande de messe),
écarts avec le SRS. Attends mon « go ».

Étape 1 — Modèle et règles (TDD, HackSoft : services/selectors, pas de logique dans les vues)
- Fund (fonds) rattaché à un nœud (paroisse, diocèse) : type quête_dominicale | quete_imperee | campagne |
  contribution_annuelle ; destination (paroisse ou curie) ; période ; objectif optionnel ; statut ; décidé par
  (office) ; référence de l'autorisation diocésaine. Une quête impérée est créée au diocèse et déclinée par paroisse.
- Donation : fonds (obligatoire, immuable : c. 1267 §3), montant en entier FCFA, frais couverts oui/non, anonyme,
  donateur nullable (don sans compte depuis la page publique), canal en_ligne | especes, statut
  initie → en_attente → confirme | echoue | expire | rembourse (machine à états stricte, journalisée).
- PaymentAttempt : fournisseur, référence externe unique, clé d'idempotence, payload brut chiffré, horodatages.
- CashCollection : saisie de quête en espèces (messe, fonds, montant, deux compteurs distincts, validée par une
  seconde personne).
- Payout / rapprochement : reversements de l'agrégateur, écarts.
- Retirer toute offrande de messe du module (migration expand/contract, aucune donnée perdue).
- Capacités (catalogue fermé, §6.2) : dons.voir_fonds, dons.gerer_fonds, dons.saisir_quete, dons.voir_donateurs,
  dons.exporter, dons.definir_quete_imperee ; attribution aux offices (curé, économe, secrétaire…) dans le
  référentiel ; `peut()` avec héritage sur le sous-arbre ; au-dessus de la paroisse : agrégats seulement.
- Garde c. 848 : aucune dépendance entre dons et documents, messaging, confession ; test qui l'affirme.

Étape 2 — Paiement
- Interface PaymentProvider (create_checkout, verify_callback, fetch_status, list_payouts) + implémentation PayDunya
  (ou l'agrégateur retenu) + FakeProvider pour les tests et la CI. Aucun secret en dur (variables d'environnement).
- Flux : POST /api/v1/dons/checkout/ → crée Donation(initie) + PaymentAttempt, renvoie l'URL de paiement de
  l'agrégateur ; retour utilisateur via lien universel ; confirmation UNIQUEMENT par le webhook (IPN) signé :
  vérification de signature, idempotence, rejeu sans double comptage, réponse rapide et traitement Celery.
- Tâche Celery de réconciliation (statuts en attente > N minutes, expirations, reversements).
- Seuils KYC BCEAO documentés (le KYC reste chez l'agrégateur).

Étape 3 — API (contrat d'abord, drf-spectacular) et règles d'accès
- Public : GET fonds ouverts d'une paroisse ; POST checkout sans compte (limitation de débit, anti-abus).
- Fidèle : mes dons, reçu (PDF simple « reçu de don », pas de reçu fiscal), anonymat respecté partout.
- Paroisse : fonds CRUD, saisie de quête, opérations (noms masqués sans dons.voir_donateurs), export CSV/XLSX,
  rapprochement. Diocèse : quêtes impérées, agrégats par paroisse. Plateforme : santé des webhooks.
- Journal d'audit (AuditEvent) sur chaque action sensible ; données de don classées sensibles (loi 2008-12) :
  minimisation, pas de montants ni de noms dans les logs ni dans Sentry.
- Drapeau JANGUBI_MODULES : `donations` activable par nœud (pilote Saint-Dominique seulement).

Étape 4 — Qualité
- Tests : machine à états, idempotence du webhook, signature invalide, montants (entiers, bornes), capacités par
  office, agrégats sans données nominatives, garde c. 848, anonymat, export. Couverture du module ≥ 90 %.
- Mets à jour le SRS (§6 capacités, §7 API, §8 cycle de vie du don), l'ADR, le schéma OpenAPI et les fixtures
  (paroisse Saint-Dominique, fonds du 27 sept. 2026, quête impérée Grand Séminaire de Brin).
- Branche feat/v1-dons, commits conventionnels, `make act` vert avant tout push vers develop ; jamais les jobs
  build-docker / trigger-deploy via act ; PR sans merge. ⏸ à la fin de chaque étape.
```
