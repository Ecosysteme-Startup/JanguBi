# Brief : échantillon web Jàngu Bi, direction « Ciel produit »

## 1. Pourquoi une nouvelle version
Le client trouve que le web actuel « ressemble à un site fait par Claude ». Il a raison. Signatures relevées sur les maquettes Ciel actuelles, **toutes interdites ici** :
- grand titre serif avec un mot en *italique bleu* (« Chaque semaine, *votre paroisse.* ») ;
- numérotation éditoriale des sections (« 01 — La Parole du jour », « I — », « II — ») et libellés « Fig. 1 », « PHOTO · … » ;
- bandeau-ticker en haut de page (date, « Jour 267 », références), filets fins partout, doubles filets ;
- colonnes de méta en petit gris, rayons quasi nuls (2 px), boutons avec flèche « → » systématique ;
- gros chiffre isolé façon rapport annuel (« 214 »), mini-graphiques décoratifs, micro-texte partout ;
- ton « revue éditoriale » appliqué à un produit.

Le mobile, lui, paraît naturel parce qu'il suit les conventions d'un **produit** : interface en sans-serif, composants familiers, cartes arrondies sur surfaces pâles, hiérarchie simple, contenus réels. **Le web doit être la même app, en grand.** Références d'esprit : les espaces web de produits sobres et soignés (type Airbnb, Doctolib, Qonto, Linear, Notion) ; pas une revue.

## 2. Règles de la direction
- **Même système que le mobile** : lis `../mobile/BRIEF-MOBILE.md` §3 (tokens EXACTS, hex majuscules, `#FEFEFE` pour le blanc fixe), §4 (typo), §6 (composants), et regarde la planche `../mobile/project/APP-H01-Design-System.dc.html` et les écrans `../mobile/project/APP-B01-Accueil.dc.html`, `APP-C01-Paroisse`, `APP-D05-Nouvelle-Infos`, `APP-E04-Conversation`, `APP-G02-Staff-Demandes` : le web en reprend composants, rayons, badges, cartes de créneau, bande de dates, pilules.
- **Typographie** : Libre Franklin partout dans l'interface (titres de page 32-40 px poids 600, sections 20-24 px 600). **Source Serif 4 réservé** au texte de la Parole, aux citations bibliques et au logotype « Jàngu Bi ». Jamais d'italique décoratif dans un titre.
- **Rayons** : cartes 16, champs et boutons 12, pilules 999. **Ombres** légères (`0 1px 2px rgba(14,26,43,0.06)` ; menus `0 8px 24px rgba(14,26,43,0.10)`).
- **Couleur** : fond `#FFFFFF`, zones de contenu secondaires `#F7FAFD`, primaire `#0A6BA3`. Un seul aplat bleu fort par écran au maximum (hero Parole ou bouton principal), pas plus.
- **Grille** : contenu max 1200 px centré (public) ; app = barre latérale 264 px + contenu fluide avec marge 40 px, max 1120 px.
- **Micro-copie** : phrases complètes et simples, pas de slogans. Pas de flèches « → » dans les boutons (icône Lucide seulement si utile).
- **Images** : emplacements photo art-dirigés comme au mobile (`data-photo-slot`), rayon 16, **sans légende « PHOTO · »** ; une légende normale en 13 px ink3 seulement si elle informe (« Église Saint-Dominique, Point E »).
- Données, personnes, dates, règles de l'Église : `../jangubi-v1/BRIEF-V1.md` §2 et §5 (identiques). Pas de confession par message, réservation sans contenu, acte = original papier à retirer, features gelées absentes.
- Format `.dc.html` : `../jangubi-v1/BRIEF-V1.md` §6 (identique), polices comme au mobile.
- Liens entre écrans : noms EXACTS de §4.

## 3. Gabarits
`templates/tpl-web-public.dc.html` (en-tête public, pied de page) et `templates/tpl-web-app.dc.html` (barre latérale fidèle ; variante paroisse décrite en commentaire). Copie le chrome, ne le réinvente pas.

## 4. Échantillon (fichiers `project/<ID>.dc.html`, largeur 1440)
Public (agent 1)
- WEB-Accueil : page d'accueil publique : hero sobre (titre clair en sans-serif, sous-titre, 2 boutons, visuel = aperçu de l'app : carte « Parole du jour » + carte « Prochaine messe » posées sur un emplacement photo), la Parole du jour (carte avec verset en Source Serif, lectures), « Trouver votre paroisse » (recherche + 3 paroisses), les 4 services présentés en rangées alternées texte/aperçu d'interface (pas de tuiles d'icônes), « Pour les paroisses » (bandeau sobre), FAQ (accordéon), pied de page. ~1440×3000
- WEB-Parole-du-jour : lectures du jour (bande de dates, onglets Lectures/Psaume/Évangile, texte en Source Serif 20/32 sur colonne 680, colonne latérale : jour liturgique, écouter, partager, calendrier du mois). ~1440×1900
- WEB-Fiche-Paroisse : Saint-Dominique (photo, infos, horaires avec bande de dates et cartes de créneau, annonces, lieux de culte avec mini-carte, clergé, contact, bouton « Suivre cette paroisse »). ~1440×2200
- WEB-Connexion : page Keycloak habillée (carte centrée 440 px sur fond #F7FAFD, logotype, e-mail, mot de passe, erreur visible, « Mot de passe oublié », « Créer un compte »). 1440×900

Espace fidèle (agent 2)
- WEB-FID-Accueil : « Bonjour Marie-Thérèse » ; hero Parole (b600, comme le mobile), prochaine messe, demande en cours avec progression, dernières annonces, conversation non lue, rendez-vous de confession. 1440×1300
- WEB-FID-Demande-Nouvelle : nouvelle demande, étape 3/4 (stepper horizontal, formulaire 2 colonnes avec un champ en erreur, colonne latérale récapitulative collante « Votre demande » + rappel original papier). 1440×1400
- WEB-FID-Conversation : messagerie 3 colonnes (barre latérale app, liste des conversations, fil avec note de confession épinglée, en-tête chiffré), composer. 1440×960

Espace paroisse (agent 3) — barre latérale paroisse (sélecteur de contexte Saint-Dominique en tête)
- WEB-PAR-Tableau-de-bord : « Aujourd'hui » pour Mme Germaine Faye : liste de tâches actionnables (comme APP-G01), file courte des demandes en retard, confessions de samedi (grille compacte de créneaux), annonce du dimanche à publier, activité de la semaine (UN graphique sobre, pas de rangée de stat cards). 1440×1300
- WEB-PAR-Demandes : table des demandes (onglets statuts avec compteurs, recherche, filtres en pilules, 12 lignes, tri, sélection multiple, pagination, ligne en retard signalée sobrement). 1440×1100
- WEB-PAR-Demande-Detail : détail JB-2026-00405 en 2 colonnes (données du registre, historique chronologique, note interne marquée « Interne », message au demandeur ; colonne d'actions : statut, changer le statut, attribuer). 1440×1200

Design system (agent 4)
- WEB-Design-System : planche web 1440×3200 : couleurs (tokens), typographie (échelle web), boutons, champs et états, sélecteurs, badges de statut, cartes, table, navigation (en-tête public, barre latérale), onglets, pilules, dialog, toast, pagination, bande de dates, carte de créneau, emplacements photo. Plus un encadré « Ce qu'on ne fait pas » avec 6 anti-exemples miniatures barrés (italique décoratif, numérotation éditoriale, ticker, stat cards, etc.).
