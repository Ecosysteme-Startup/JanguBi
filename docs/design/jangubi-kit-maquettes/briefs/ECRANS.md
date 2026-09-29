# Écrans de l'app mobile Jàngu Bi (thème Ciel)

Tailles par défaut : iOS 390×844 ; écran qui défile : hauteur ajustée au contenu (jusqu'à 1500). Android 412×915.
Onglet actif de la tab bar indiqué entre crochets.

## Lot A — Démarrage et compte (agent A)
- APP-A01-Lancement : écran de lancement (logotype Jàngu Bi en Source Serif sur b600, sous-titre « La Parole, ta paroisse, tes démarches »), 390×844
- APP-A02-Bienvenue-1 : onboarding 1/3 « La Parole du jour » (emplacement photo, pagination à points, Passer / Continuer), 390×844
- APP-A03-Bienvenue-2 : onboarding 2/3 « Ta paroisse dans ta poche » (horaires, annonces), 390×844
- APP-A04-Bienvenue-3 : onboarding 3/3 « Tes démarches, suivies » + « Parler à un prêtre » ; boutons « Créer un compte » / « J'ai déjà un compte », 390×844
- APP-A05-Connexion : feuille d'authentification Keycloak ouverte dans le navigateur intégré (ASWebAuthenticationSession : bandeau système « “Jàngu Bi” souhaite utiliser “auth.jangubi.sn” pour se connecter » puis page habillée : e-mail, mot de passe, « Mot de passe oublié ? », « Se connecter », séparateur, « Créer un compte »), 390×844
- APP-A06-Inscription : création de compte étape 1/3 (prénom, nom, e-mail avec validation OK, date de naissance avec aide « Certaines fonctions sont réservées aux majeurs », mot de passe avec jauge, un champ en erreur visible), 390×1000
- APP-A07-Choix-Paroisse : étape 2/3 : recherche + « Autour de moi » + liste de paroisses (Saint-Dominique sélectionnée, diocèse, doyenné, distance), 390×1000
- APP-A08-Consentement : étape 3/3 : récapitulatif + consentements (loi 2008-12, données sensibles : appartenance religieuse), cases séparées et non pré-cochées, lien politique de confidentialité, « Terminer », 390×1000
- APP-A09-Notifications-Permission : écran d'amorçage avant la demande système (quoi et quand : annonces de ta paroisse, suivi des demandes, réponses du prêtre), + boîte de dialogue iOS système simulée sur voile, 390×844

## Lot B — Accueil et Parole (agent B)
- APP-B01-Accueil [Accueil] : salutation « Bonjour Marie-Thérèse », jour liturgique (carte hero b600 : jeudi 24 septembre, 25e semaine du T.O., pastille verte, versets du jour, « Lire la Parole »), prochaine messe à Saint-Dominique (18 h 30), dernière annonce, suivi de la demande JB-2026-00412 (progression), raccourci « Parler à un prêtre », 390×1400
- APP-B02-Notifications : liste groupée Aujourd'hui / Cette semaine, non lues marquées, balayage « Marquer comme lu » montré sur une rangée, 390×1000
- APP-B03-Recherche : recherche globale (champ actif, clavier iOS NON dessiné, suggestions récentes, résultats groupés : Bible, Paroisses, Annonces), 390×900
- APP-B04-Parole [Parole] : Parole du jour : sélecteur de date (bande de dates), segmented « Lectures · Psaume · Évangile », première lecture Ec 1, 2-11 en Source Serif 19/30 (versets numérotés), boutons Écouter / Partager / Enregistrer, 390×1500
- APP-B05-Lecture-Evangile : mode lecture plein écran de l'Évangile Lc 9, 7-9 (barre minimale, réglage taille de texte en bottom sheet ouverte : curseur A-/A+, thème clair/sépia/sombre, police serif), 390×844
- APP-B06-Bible-Livres [Parole] : Bible : segmented Ancien / Nouveau Testament, recherche, liste groupée des livres par section (Pentateuque, Livres historiques…), dernier passage lu en tête, 390×1300
- APP-B07-Bible-Chapitre : Évangile selon saint Luc, chapitre 9 : sélecteur de chapitres horizontal, texte, verset surligné avec menu contextuel (Copier, Surligner, Partager, Signet), 390×1200
- APP-B08-Chapelet [Parole] : chapelet personnel : mystères du jour (jeudi = lumineux), progression par dizaine (grains cliquables, 3e dizaine en cours), texte de la prière en cours, boutons Précédent / Suivant, 390×1000
- APP-B09-Calendrier-Liturgique : calendrier mensuel septembre 2026 avec pastilles de couleur liturgique par jour (vert par défaut ; 8 sept. Nativité de la Vierge Marie blanc ; 14 sept. Croix glorieuse rouge ; 21 sept. saint Matthieu rouge ; 29 sept. saints Michel, Gabriel et Raphaël blanc ; 30 sept. saint Jérôme blanc ; 27 sept. 26e dimanche vert ; aujourd'hui 24 cerclé ; pour le blanc, pastille blanche cerclée litGold `#9A7A2C` ; rouge `#A3262A`), fêtes listées sous le calendrier, 390×1100

## Lot C — Ma paroisse (agent C)
- APP-C01-Paroisse [Paroisse] : Paroisse Saint-Dominique : en-tête (photo slot, nom, Point E, doyenné Plateau-Médina, bouton « Suivie »), prochaines messes (3 cartes de créneau), annonces du dimanche (3), lieux de culte (2), contact (téléphone, itinéraire), clergé (curé, vicaires), 390×1600
- APP-C02-Horaires [Paroisse] : horaires des messes : bande de dates (jeu. 24 sélectionné), filtre par lieu (pilules), liste de créneaux (messe, confessions, adoration) avec heure à gauche, « Ajouter au calendrier », 390×1100
- APP-C03-Annonces [Paroisse] : annonces : pilules (Toutes · Liturgie · Catéchèse · Vie de la paroisse · CEB), liste de cartes (date, titre, extrait, épinglée), 390×1200
- APP-C04-Annonce-Detail : Quête impérée pour le Grand Séminaire de Brin : titre Source Serif, méta, corps, bloc info, Partager, 390×1100
- APP-C05-Agenda [Paroisse] : agenda : calendrier mensuel (octobre 2026) avec points, jour sélectionné (dim. 4 oct.), liste des événements du jour, segmented Mois / Liste, 390×1100
- APP-C06-Evenement-Detail : Messe d'action de grâce pour la rentrée universitaire : date, heure, lieu (mini-carte schématique SVG), description, « Ajouter au calendrier », « Itinéraire », 390×1100
- APP-C07-Annuaire : annuaire des paroisses : recherche, segmented Liste / Carte, filtres (diocèse, doyenné), liste avec distance, 390×1100
- APP-C08-Annuaire-Carte : vue carte schématique de Dakar (SVG sobre : côte, routes, pins b600, pin sélectionné) + bottom sheet partielle avec la fiche courte de Cathédrale Notre-Dame-des-Victoires, 390×844
- APP-C09-Changer-Paroisse : bottom sheet « Paroisse suivie » (paroisse actuelle, rechercher, confirmation) sur l'écran Paroisse assombri, 390×844

## Lot D — Demandes d'actes (agent D)
- APP-D01-Demandes [Demandes] : mes demandes : pilules (En cours · Terminées), liste (JB-2026-00412 Extrait d'acte de baptême, En vérification ; JB-2026-00398 Attestation de confirmation, Prête à retirer ; une Complément demandé), bouton « Nouvelle demande », 390×1000
- APP-D02-Demandes-Vide [Demandes] : état vide (illustration SVG sobre, explication en 2 phrases, bouton), 390×844
- APP-D03-Nouvelle-Type : nouvelle demande 1/4 : choix du type d'acte (cartes radio : extrait d'acte de baptême, attestation de confirmation, attestation de mariage religieux, certificat de première communion, attestation de parrain/marraine), stepper en tête, 390×1000
- APP-D04-Nouvelle-Paroisse : 2/4 : paroisse du sacrement (explication claire : « la demande part à la paroisse où le sacrement a été célébré »), recherche, Sainte-Thérèse de Grand-Dakar sélectionnée, case « je ne connais pas la paroisse » avec aide, 390×1000
- APP-D05-Nouvelle-Infos : 3/4 : informations (nom et prénoms au moment du baptême, date approximative avec sélecteur date iOS en roue affiché en bottom sheet, parents, motif : pour mariage, mode de retrait : retrait sur place / par un tiers mandaté), un champ en erreur, 390×1300
- APP-D06-Nouvelle-Recap : 4/4 : récapitulatif, rappel « L'extrait est un original papier signé et scellé, à retirer à la paroisse. Aucun document n'est envoyé par l'application. », case d'attestation, « Envoyer la demande », 390×1100
- APP-D07-Demande-Envoyee : succès : référence JB-2026-00421, prochaines étapes, délai indicatif, « Suivre ma demande », 390×844
- APP-D08-Demande-Suivi : suivi JB-2026-00412 : statut actuel, frise chronologique verticale (Soumise 18 sept. → En vérification 19 sept. → Complément demandé → …), message de la paroisse, adresse et horaires de retrait, 390×1200
- APP-D09-Complement : réponse à un complément demandé (message de Mme Germaine Faye, champ réponse, ajout de pièce : photo de la page du livret de famille, pièce jointe listée), 390×1000

## Lot E — Parler à un prêtre (agent E)
- APP-E01-Pretre [Prêtre] : onglet Prêtre : segmented Conversations / Prêtres ; bandeau permanent « La confession ne se fait pas par message… Prendre rendez-vous » ; liste de conversations (Abbé Augustin Ndiaye, Père Emmanuel Tine), indicateur non lu, cadenas « chiffré », 390×1000
- APP-E02-Pretres-Liste [Prêtre] : prêtres joignables de Saint-Dominique (avatar initiales, office : curé / vicaire, disponibilité « Répond en général sous 24 h »), 390×1000
- APP-E03-Pretre-Profil : Abbé Augustin Ndiaye, curé : office, paroisse, horaires de permanence, boutons « Écrire » et « Rendez-vous de confession », 390×1000
- APP-E04-Conversation : conversation avec Père Emmanuel Tine : en-tête (avatar, nom, « Chiffré de bout en bout »), note de confession épinglée non masquable (compacte), bulles (fidèle b600 texte blanc à droite, prêtre surface à gauche), séparateur de date, accusés de lecture, composer (champ + envoi), 390×844
- APP-E05-Chiffrement : vérification de sécurité : code de sécurité à 60 chiffres en 12 groupes, QR code SVG, explication, « Marquer comme vérifié », 390×1000
- APP-E06-Messagerie-Refus : messagerie indisponible pour un compte mineur : explication bienveillante, alternatives (horaires de permanence, téléphone du secrétariat, rendez-vous accompagné), 390×844
- APP-E07-Confession-Creneau : rendez-vous de confession : prêtre (Tous / Abbé Ndiaye / Père Tine / Abbé Sagna), calendrier (samedi 26 sept. sélectionné), grille de créneaux de 10 min (16 h 00 → 17 h 50, certains complets), lieu (église Saint-Dominique, confessionnal côté sacristie), note « aucun motif n'est demandé », bouton « Réserver 16 h 20 », 390×1200
- APP-E08-Confession-Confirmee : confirmation : carte de rendez-vous, rappel la veille, « Ajouter au calendrier », « Annuler le rendez-vous » (destructif), 390×844
- APP-E09-Mes-Rendez-vous : mes rendez-vous (à venir, passés sans détail), action sheet iOS « Annuler ce rendez-vous ? » ouverte, 390×844

## Lot F — Profil, réglages, états (agent F)
- APP-F01-Profil : profil (avatar, nom, e-mail, paroisse suivie), listes groupées : Mon compte, Paroisse suivie, Rendez-vous, Notifications, Apparence, Sécurité et appareils, Confidentialité, Aide, À propos, Déconnexion (destructif), 390×1300
- APP-F02-Apparence : thème (Système / Clair / Sombre en cartes aperçu), taille du texte (curseur + aperçu Source Serif), langue (Français ; Wolof « bientôt » désactivé), 390×1000
- APP-F03-Notifications-Reglages : switches par catégorie (Annonces de ma paroisse, Suivi des demandes, Messages des prêtres, Rappels de rendez-vous, Parole du jour avec heure 7 h 00), 390×1000
- APP-F04-Securite : sécurité et appareils : Face ID pour ouvrir l'app (switch), appareils connectés (iPhone 15 — cet appareil, iPad), clés de chiffrement (sauvegarde de la clé de récupération, statut « sauvegardée »), déconnecter partout, 390×1100
- APP-F05-Confidentialite : données personnelles : ce que nous conservons, consentements (modifiables), « Télécharger mes données », « Supprimer mon compte » (destructif, explication des conséquences), 390×1100
- APP-F06-Hors-Ligne [Parole] : bannière hors ligne en haut, contenu en cache (Parole du jour disponible hors ligne), actions réseau désactivées, 390×844
- APP-F07-Chargement [Accueil] : squelettes de l'accueil (skeleton surface2), 390×844
- APP-F08-Erreur : erreur serveur avec « Réessayer » et référence technique discrète, 390×844
- APP-F09-Mise-a-jour : mise à jour requise (version 1.2.0 → store), 390×844

## Lot G — Staff (secrétariat et prêtres, mêmes app, espace « Paroisse Saint-Dominique » via bascule de contexte) (agent G)
- APP-G01-Staff-Accueil : bascule de contexte en tête (« Fidèle · Espace paroisse Saint-Dominique »), aujourd'hui : 4 demandes à traiter (2 en retard), 3 messages sans réponse, 12 rendez-vous samedi, publication à venir ; tab bar staff : Aujourd'hui · Demandes · Messages · Agenda · Plus, 390×1200
- APP-G02-Staff-Demandes : file des demandes (pilules de statut, compteurs, tri, rangées avec référence, type, demandeur, âge de la demande, en retard marqué), 390×1200
- APP-G03-Staff-Demande-Detail : détail JB-2026-00412 (données, historique, note interne visible seulement du staff, actions : Demander un complément / Marquer prête à retirer), bottom sheet de changement de statut ouverte, 390×1100
- APP-G04-Staff-Messages : messagerie du prêtre (Abbé Ndiaye) : conversations, filtres Non lues / Toutes, rappel déontologique (pas de confession par message), 390×1000
- APP-G05-Staff-Confessions : créneaux de confession du samedi : grille de créneaux avec nombre de réservés (sans nom ni motif visible au-delà du prénom), bouton « Ouvrir des créneaux », 390×1100
- APP-G06-Staff-Annonce : publier une annonce (titre, catégorie, texte, date de publication, épingler, aperçu), 390×1200
- APP-G07-Staff-MFA : vérification en deux étapes à la connexion staff (code à 6 chiffres TOTP, champ segmenté, « Utiliser un code de secours »), 390×844

## Lot H — Android + design system (agent H)
- APP-H01-Design-System : planche des composants mobiles (palette Ciel clair, typographie, boutons, champs états, checkbox/radio/switch, badges de statut, cartes, liste groupée, bande de dates, carte de créneau, tab bar iOS, navigation bar Android, bottom sheet, dialog, toast, skeleton), 1200×2200 (planche, pas un écran de téléphone)
- AND-H02-Accueil : accueil Android (Material 3 : top app bar, contenu identique à APP-B01 adapté, navigation bar M3), 412×1400
- AND-H03-Parole : Parole du jour Android, 412×1300
- AND-H04-Nouvelle-Demande : étape 3/4 Android avec date picker Material 3 (dialog calendrier) ouvert, 412×915
- AND-H05-Conversation : conversation Android, 412×915
- AND-H06-Confession-Creneau : réservation Android, 412×1100
- AND-H07-Profil : profil Android (listes Material, switches M3), 412×1200
