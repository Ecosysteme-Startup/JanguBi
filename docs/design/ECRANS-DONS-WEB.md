# Écrans web — Dons et quêtes (direction « Ciel produit »)

> Version du 27/09/2026. Canvas « Jàngu Bi — Web · Ciel produit » (claude.ai/artifact/NMrbMhcbbFaTXXojoXg8Az).
> Sources : `docs/design/PROMPTS-DONS.md` (prompt 1), `docs/design/dons-quetes-etude.md`, cadrage `docs/v1/conception/DONS-00-cadrage.md`, API de la PR #33 (`schema.yml`).
> Format, tokens et interdits : kit `jangubi-kit-maquettes` (BRIEF-V1 §5-§6, BRIEF-MOBILE §3-§4-§6, BRIEF-WEB-CIEL §1-§2). Largeur 1440, hauteur = contenu.

## 0. Règles propres au module

- **Hypothèses retenues** (validées le 27/09) : H1 l'archidiocèse encaisse, clé d'affectation par paroisse ; H2 quête dominicale, quête impérée (curie), campagne, contribution annuelle, **aucune offrande de messe** ; H3 frais affichés, case « Je couvre les frais » **décochée**, sinon déduits ; H4 autorisation écrite supposée obtenue, mention visible.
- **c. 848** : aucun appel au don dans les écrans de demande d'acte, de confession et de messagerie ; aucune mise à jour de ces écrans.
- **Paiement** : jamais de faux formulaire de carte ni de numéro de téléphone Wave/OM dans Jàngu Bi ; on montre la redirection vers la page de l'agrégateur et le retour.
- **Données** : aucun classement, aucun « donateur du mois », aucune liste publique ; noms visibles du curé et de l'économe seulement ; au diocèse, des sommes par paroisse.
- **Micro-copie** : sobre, jamais culpabilisante (pas de « Sans vous, rien n'est possible », pas de compte à rebours, pas de « Plus que 3 jours ! »). Montants « 5 000 FCFA » avec espaces insécables, chiffres tabulaires.
- **Capacités** : les noms du backend font foi (`dons.voir_fonds`, `dons.gerer_fonds`, `dons.saisir_quete`, `dons.voir_donateurs`, `dons.exporter`, `dons.definir_quete_imperee`).
- **Pas de jauge-thermomètre** : l'avancement d'une campagne est une barre de progression du design system (h 6, rayon 3, piste surface2, remplissage b600) avec le chiffre à côté.

## 1. Chrome

| Espace | Barre latérale | Entrée ajoutée |
|---|---|---|
| Fidèle (gabarit `tpl-web-app`) | Accueil · La Parole · Ma paroisse · Mes demandes · Parler à un prêtre | **Dons** (icône Lucide `hand-heart`), en dernier |
| Paroisse (variante de WEB-PAR-Tableau-de-bord) | Aujourd'hui · Demandes d'actes · Messagerie · Confessions · Annonces · Horaires et lieux · Agenda · Équipe · Paramètres | **Dons et quêtes**, après Agenda |
| Diocèse | Tableau de bord · Structure · Nominations · Clergé · Paramètres | **Quêtes impérées**, après Clergé |
| Plateforme | Tableau de bord · Référentiels · Comptes · Journal d'audit | **Paiements**, après Comptes |

L'entrée est ajoutée **partout**, y compris aux 45 écrans existants et à leurs versions sombres (script). « Dons » en dernier côté fidèle (discret, jamais voisin des parcours pastoraux, c. 848 ; accès principal par le bloc « Soutenir la paroisse » de Ma paroisse, comme sur mobile) ; « Dons et quêtes » après « Agenda » côté paroisse, avec les outils de gestion.

## 2. Données de référence

- **Fidèle** : Marie-Thérèse Diouf, jeudi 24 septembre 2026. **Paroisse, diocèse, plateforme** : lundi 28 septembre 2026 (lendemain des quêtes du dimanche 27).
- **Autorisation** : « Collecte autorisée par l'Archevêché de Dakar, décision du 1er septembre 2026 (réf. ARCH-DAK-2026-041). »
- **Fonds ouverts à Saint-Dominique** :
  | Fonds | Type | Destination | Période | Objectif |
  |---|---|---|---|---|
  | Quête du dimanche 27 septembre | quête dominicale | paroisse | 26 sept. → 4 oct. | — |
  | Quête impérée pour le Grand Séminaire de Brin | quête impérée | curie | 27 sept. → 4 oct. | — |
  | Toiture de la chapelle de la Cité universitaire | campagne | paroisse | 1er sept. → 31 déc. | 4 500 000 FCFA ; réuni 1 186 400 FCFA (26 %), 57 dons |
  | Contribution annuelle 2026 | contribution annuelle | paroisse | 1er janv. → 31 déc. | — |
- **Montants suggérés** : 1 000 · 2 000 · 5 000 · 10 000 FCFA + montant libre ; frais estimés 2 % (100 FCFA pour 5 000).
- **Moyens acceptés** (sur la page de l'agrégateur) : Wave, Orange Money, Free Money, carte bancaire.
- **Numérotation** (sur le modèle d'un reçu de paiement) : **référence du don** en chiffres aléatoires groupés par quatre, attribuée à la création et transmise à l'agrégateur (ex. `4817-2093-6651`) ; **numéro de reçu** comptable, sans trou, attribué seulement à la confirmation : code de la paroisse, année, compteur (ex. `SD-2026-00147`).
- **Quêtes en espèces du dimanche 27** : samedi 18 h 30 (messe anticipée) 64 150 ; 7 h 30 142 350 ; 9 h 30 (étudiants) 96 725 ; 11 h 30 231 900 ; 18 h 30 118 400 FCFA. Compteurs : Pierre Ndour et Thérèse Ndione, Joseph Mendy et Cécile Coly.
- **Synthèse de septembre (paroisse)** : 1 214 830 FCFA affectés, dont en ligne 356 330 (47 dons) et espèces 858 500 ; frais 7 120 ; 3 paiements en attente ; 1 saisie à valider.
- **Économe paroissiale** : Mme Cécile Coly (office « Économe paroissial ») ; curé : Abbé Augustin Ndiaye ; secrétaire : Mme Germaine Faye.
- **Diocèse** : économe diocésain M. Albert Senghor ; Saint-Dominique seule paroisse où la collecte est ouverte, 4 paroisses en préparation.

## 3. Écrans

Chaque ligne : ID (fichier `<ID>.dc.html`) · taille indicative · contenu · états montrés · liens.

### Fidèle (barre latérale fidèle, entrée « Dons » active)

1. **WEB-FID-Donner** · 1440×1400
   - En-tête : « Soutenir la paroisse Saint-Dominique », une phrase simple (« Votre don est affecté au fonds que vous choisissez. »), mention d'autorisation diocésaine avec icône `shield-check`.
   - Colonne gauche (formulaire, étapes visibles sans stepper) : **1. Fonds** (cartes radio : les 4 fonds ; la campagne montre sa barre d'avancement ; la quête impérée porte le badge « Reversée au diocèse ») ; **2. Montant** (pilules 1 000/2 000/5 000/10 000, 5 000 sélectionné, champ « Autre montant » avec aide « Entre 100 et 1 000 000 FCFA ») ; **3. Options** (case « Je couvre les frais de paiement (100 FCFA) » décochée, case « Don anonyme » avec aide « Votre nom n'apparaîtra nulle part, même pour la paroisse. »).
   - Colonne droite collante « Votre don » : fonds, don 5 000, frais estimés 100 « déduits du don », affecté 4 900, bouton principal « Continuer vers le paiement », ligne « Paiement sécurisé chez un prestataire agréé BCEAO. Jàngu Bi ne conserve aucune donnée de paiement. », logos texte des moyens (pas d'images de marque : pilules texte).
   - État : sélection normale (fonds « Quête du dimanche », 5 000 FCFA) ; l'erreur de montant est montrée sur WEB-Don-Paroisse.
   - Liens : Continuer → WEB-FID-Don-Redirection ; carte campagne « Voir la campagne » → WEB-FID-Campagne ; « Mes dons » → WEB-FID-Mes-Dons.
2. **WEB-FID-Don-Redirection** · 1440×900
   - Carte centrée (560) : « Vous allez être redirigé vers la page de paiement sécurisée », récapitulatif (fonds, 5 000 FCFA, frais), 3 étapes numérotées en liste simple (vous choisissez Wave, Orange Money, Free Money ou la carte ; vous validez chez l'opérateur ; vous revenez automatiquement sur Jàngu Bi), barre de progression indéterminée sobre « Ouverture de la page de paiement… », lien « La page ne s'ouvre pas ? Continuer » et « Annuler ».
   - Liens : Continuer → WEB-FID-Don-Confirmation ; Annuler → WEB-FID-Donner.
3. **WEB-FID-Don-Confirmation** · 1440×1100
   - Succès : icône `circle-check` okT, « Merci, votre don est confirmé. », référence 4817-2093-6651, numéro de reçu SD-2026-00147, fonds, montant, moyen (Wave), date ; bouton « Télécharger le reçu » (secondaire) + « Retour à l'accueil » ; note « Reçu simple : ce n'est pas un reçu fiscal. »
   - Variante en encadré (Alert warn) sous le succès : « Paiement en attente de confirmation » : l'opérateur n'a pas encore confirmé ; ne pas refaire le paiement ; la page se met à jour ; délai habituel quelques minutes ; lien « Voir mes dons ».
   - Liens : WEB-FID-Mes-Dons, WEB-FID-Accueil.
4. **WEB-FID-Mes-Dons** · 1440×1200
   - Titre « Mes dons », total de l'année « 2026 : 38 500 FCFA, 7 dons » avec mention « Visible par vous seul. »
   - Filtres : pilules par fonds (Tous, Quêtes, Campagnes, Contribution), sélecteur d'année.
   - Table-cartes (10 lignes) : date, fonds, paroisse, montant, statut (badges : Confirmé, En attente, Échoué, Remboursé), anonymat (icône `eye-off` si anonyme), action « Reçu » (désactivée sauf Confirmé, info-bulle « Disponible une fois le don confirmé »).
   - Liens : Nouveau don → WEB-FID-Donner.
5. **WEB-FID-Campagne** · 1440×1500
   - Emplacement photo `data-photo-slot="chapelle-cite-universitaire"` (rayon 16), titre, paroisse, période, barre d'avancement (1 186 400 / 4 500 000 FCFA, 26 %, 57 dons), « Usage des fonds » (liste : charpente, tôles, gouttières, main-d'œuvre, avec montants budgétés), « Nouvelles de la campagne » (2 messages de l'Abbé Augustin Ndiaye, datés), colonne droite : bouton « Donner à cette campagne », mention d'autorisation, « Les dons sont affectés à ce seul projet. La collecte se ferme dès que l'objectif est atteint. »
   - Liens : Donner → WEB-FID-Donner.

### Public (en-tête public du gabarit `tpl-web-public`)

6. **WEB-Don-Paroisse** · 1440×1300
   - La page qu'ouvre l'app mobile dans Safari : en-tête public, bloc paroisse (nom, quartier), mention d'autorisation, formulaire compact sur une colonne de 640 : fonds (liste radio), montant (pilules + libre, **champ « Autre montant » en erreur** : « Le montant minimum est de 100 FCFA. »), options (frais, anonyme), e-mail facultatif « pour recevoir votre reçu (effacé après 90 jours) », bouton « Continuer vers le paiement » ; lien « Se connecter pour retrouver ce don dans Mes dons ».
   - Pas de compte obligatoire. Pied de page public.
   - Liens : WEB-FID-Don-Redirection (même parcours), WEB-Connexion, WEB-Fiche-Paroisse.

### Paroisse (barre latérale paroisse, « Dons et quêtes » actif ; en-tête contexte Saint-Dominique ; utilisatrice : Mme Cécile Coly, économe)

7. **WEB-PAR-Dons** · 1440×1450
   - Titre « Dons et quêtes », sélecteur de mois (septembre 2026), boutons « Saisir une quête » (principal) et « Nouvelle campagne ».
   - Ligne de synthèse **en texte** (pas de stat cards) : « 1 214 830 FCFA affectés en septembre, dont 356 330 en ligne et 858 500 en espèces. » + 2 alertes compactes (3 paiements en attente, 1 quête à valider → lien).
   - **Un seul graphique** : barres par dimanche (en ligne / espèces, 2 tons de bleu, légende), axe sobre.
   - « Par fonds » : liste (fonds, type, affecté ce mois, total, statut) ; « Par moyen » : liste courte (Wave, Orange Money, Carte, Espèces).
   - « Dernières opérations » : table 10 lignes (date, référence, fonds, montant, moyen, statut, donateur). Donateurs : « Élisabeth Gomis », « Anonyme », « Donateur sans compte », « Quête en espèces » (vue économe, qui a `dons.voir_donateurs`), + note « Les noms ne sont visibles que du curé et de l'économe. »
   - « Reversements » : encadré info « Les reversements de l'agrégateur arrivent sur le compte de l'archidiocèse. Montant affecté à la paroisse en septembre : 349 210 FCFA, dont 301 480 déjà reversés. »
   - Liens : WEB-PAR-Quete-Saisie, WEB-PAR-Campagne-Editeur, WEB-PAR-Dons-Export.
8. **WEB-PAR-Campagne-Editeur** · 1440×1400
   - Formulaire : titre, usage des fonds (zone de texte), objectif (FCFA), dates début/fin (date de fin **en erreur** : « La fin doit suivre le début. »), visuel (zone de dépôt + vignette), référence d'autorisation, « Publier maintenant » / « Enregistrer en brouillon ».
   - Colonne droite : aperçu de la carte campagne telle que vue par les fidèles (web et mobile).
   - Liens : Annuler → WEB-PAR-Dons.
9. **WEB-PAR-Quete-Saisie** · 1440×1300
   - Formulaire : date de la messe (dim. 27 sept.), messe (sélecteur : horaires de Saint-Dominique), lieu, fonds (Quête du dimanche 27 septembre / Quête impérée Brin), montant compté, **deux compteurs** (champs distincts, aide « Deux personnes différentes »), observation ; bouton « Enregistrer la saisie », rappel « Une autre personne valide la saisie ».
   - Historique : table des saisies du week-end (messe, fonds, montant, compteurs, saisie par, statut : Validée / À valider / Rejetée avec motif), action « Valider » sur la ligne « À valider » saisie par Mme Germaine Faye.
   - Liens : retour WEB-PAR-Dons.
10. **WEB-PAR-Dons-Export** · 1440×1200
    - Période (du 1er au 30 sept.), fonds (tous), format (CSV / Excel, pilules), bouton « Exporter » ; note « L'export est inscrit au journal d'audit. »
    - Rapprochement : lignes « Payé en ligne », « Frais », « Affecté en ligne », « Espèces », « Reversé (archidiocèse) », « En attente de reversement ».
    - « Écarts signalés » : 3 lignes (paiement en attente depuis plus de 24 h 3302-7718-0459, quête non validée du 20 sept., reversement PO-2026-0914 avec écart de 2 940 FCFA) avec action.
    - Liens : WEB-PAR-Dons.

### Diocèse et plateforme

11. **WEB-DIO-Quetes-Imperees** · 1440×1300 (utilisateur : M. Albert Senghor, économe diocésain)
    - Liste des quêtes impérées (Grand Séminaire de Brin 27 sept., Missions 18 oct. à venir, Carême de partage 2026 clos), sélection Brin.
    - Formulaire « Définir une quête impérée » en panneau latéral ouvert : objet, date, fin de collecte, paroisses concernées (Toutes les paroisses où la collecte est ouverte / choix), référence de la décision de l'Ordinaire, « Publier ».
    - Suivi par paroisse (agrégats seulement) : Saint-Dominique (en ligne, espèces, nombre de dons, total) ; 4 paroisses en préparation « Collecte non ouverte sur Jàngu Bi » ; mention « Aucune donnée nominative à ce niveau. »
    - Reversements reçus : 3 lignes (référence, date, net, statut Rapproché / Écart).
12. **WEB-PLA-Paiements** · 1440×1150 (utilisateur : Moustoifa Ben)
    - Agrégateur « PayDunya · mode test » (nom du prestataire configuré), dernière notification il y a 4 min.
    - Notifications (webhooks) sur 24 h / 7 jours : reçues, traitées, doublons, rejetées (signature), erreurs ; en liste sobre + un graphique de volume par jour.
    - Paiements en attente (3, le plus ancien depuis 26 h), reversements à rapprocher (1), écarts (1).
    - Incidents : 4 lignes (heure, type : signature invalide, montant incohérent, paiement tardif, agrégateur injoignable ; action recommandée). Aucun nom ni montant par donateur.

### Mises à jour d'écrans existants

13. **WEB-Design-System** : section « Statuts de paiement » (badges : Initié ink/surface2, En attente warn, Confirmé ok, Échoué err, Remboursé ink3/surface2, Expiré ink3), carte de fonds, barre d'avancement, pilules de montant.
14. **WEB-FID-Ma-Paroisse** : bloc sobre « Soutenir la paroisse » dans la colonne droite (une phrase, lien « Faire un don » → WEB-FID-Donner, mention d'autorisation), sous « Contact ».
15. **WEB-Fiche-Paroisse** : même bloc, lien vers WEB-Don-Paroisse.

## 4. Variantes sombres et canvas

- `build_dark.py` sur les 12 nouveaux écrans et les 3 mis à jour (préfixe `Sombre-`).
- Canvas : pages « 13 · Dons et quêtes — clair » et « 14 · Dons et quêtes — sombre » (ordre : fidèle, public, paroisse, diocèse, plateforme ; 80 px entre cadres) ; `Main.dc.html` gagne une rangée « Dons et quêtes » ; seuls les fichiers nouveaux ou modifiés sont envoyés ; `canvas.json` relu juste avant l'envoi.

## 5. Contrôles avant publication

`support.js` exact, `class Component extends DCLogic`, `$preview` = taille racine, aucun hex hors tokens (tableau BRIEF-MOBILE §3), liens vers des fichiers existants, captures `shot.py` relues une à une (retours à la ligne, `&nbsp;` dans « 5 000 FCFA », « 18 h 30 », avant « : ? ! »).

## 6. Décisions du 27/09/2026

1. Entrée « Dons » ajoutée aux 45 écrans existants et à leurs versions sombres (script).
2. Place : dernière entrée côté fidèle, après « Agenda » côté paroisse.
3. Campagne : la collecte se ferme dès que l'objectif est atteint (backend à aligner : clôture automatique).
4. Numérotation : référence aléatoire `4817-2093-6651` + numéro de reçu séquentiel `SD-2026-00147` (backend à aligner).
5. Plateforme : nom du prestataire configuré (« PayDunya · mode test »).
6. Au passage, les écrans existants remplacent « chiffrés de bout en bout » par « Messages chiffrés, aucun administrateur n'y a accès ».
