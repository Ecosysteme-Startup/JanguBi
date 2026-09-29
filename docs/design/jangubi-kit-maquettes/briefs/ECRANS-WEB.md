# Écrans web complets, direction « Ciel produit »

Déjà faits (référence de style, à LIRE avant de commencer) : `project/WEB-Accueil`, `WEB-Parole-du-jour`, `WEB-Fiche-Paroisse`, `WEB-Connexion`, `WEB-FID-Accueil`, `WEB-FID-Demande-Nouvelle`, `WEB-FID-Conversation`, `WEB-PAR-Tableau-de-bord`, `WEB-PAR-Demandes`, `WEB-PAR-Demande-Detail`, `WEB-Design-System`. Copie leur chrome (en-tête public ou barre latérale) à l'identique, en déplaçant l'entrée active.

Largeur 1440 ; hauteur = contenu. Noms EXACTS ci-dessous (+ `.dc.html`).

## Lot P — Public et inscription (agent P)
- WEB-Paroisses : annuaire : recherche, filtres (diocèse, doyenné, « sur Jàngu Bi »), liste de 10 paroisses à gauche (carte compacte : nom, quartier, doyenné, statut Jàngu Bi, prochaine messe si active), carte schématique de Dakar à droite (SVG sobre, pins), pagination. ~1440×1300
- WEB-Pour-les-paroisses : page d'offre aux paroisses et diocèses : hero sobre, ce que la paroisse gagne (3 rangées texte + aperçu d'interface réel), déroulé du pilote en 4 étapes (frise horizontale simple), rôles et sécurité (offices, double authentification, pas d'accès au contenu des messages), FAQ, formulaire de contact complet (nom, fonction, paroisse ou diocèse, téléphone, e-mail, message, consentement, un champ en erreur). ~1440×3200
- WEB-Inscription-Compte : étape 1/3 : mise en page 2 colonnes (formulaire à gauche 480 px : prénom, nom, e-mail validé, téléphone optionnel, date de naissance avec aide majorité, mot de passe + jauge, un champ en erreur ; à droite panneau #F7FAFD : ce que le compte permet, rassurance données). Stepper 3 étapes. 1440×1000
- WEB-Inscription-Paroisse : étape 2/3 : choisir la paroisse suivie (recherche, liste radio avec Saint-Dominique sélectionnée, « Ma paroisse n'est pas encore sur Jàngu Bi » → message), 1440×1000
- WEB-Inscription-Consentement : étape 3/3 : récapitulatif + consentements séparés non pré-cochés (loi 2008-12 ; appartenance religieuse = donnée sensible ; notifications), lien politique de confidentialité, « Créer mon compte ». 1440×1000
- WEB-Erreur-404 : page introuvable dans le chrome public : message simple, recherche, liens utiles (Parole du jour, trouver une paroisse, aide). 1440×900

## Lot F1 — Espace fidèle : Parole et paroisse (agent F1)
- WEB-FID-Parole : la Parole du jour dans l'espace connecté (barre latérale « La Parole » active) : bande de dates, onglets Lectures/Psaume/Évangile, texte Source Serif colonne 680, colonne droite : jour liturgique, écouter, mes signets. ~1440×1700
- WEB-FID-Bible : Bible : colonne livres (AT/NT, recherche) + lecture de Luc 9 avec un verset surligné et son menu (Copier, Surligner, Partager, Signet), sélecteur de chapitres. 1440×1100
- WEB-FID-Chapelet : chapelet personnel : mystères lumineux (jeudi), progression par dizaine (grains), prière en cours en Source Serif, Précédent/Suivant, liste des 5 mystères à droite. 1440×1000
- WEB-FID-Ma-Paroisse : Saint-Dominique vue fidèle : en-tête paroisse (photo, suivie), onglets Aperçu/Horaires/Annonces/Agenda, prochaines messes, annonces récentes, événements, lieux de culte, clergé, contact. ~1440×1600
- WEB-FID-Annonce : détail « Quête impérée pour le Grand Séminaire de Brin » (fil d'Ariane, auteur, date, corps, encadré pratique, annonces liées). ~1440×1200
- WEB-FID-Evenement : détail « Messe d'action de grâce pour la rentrée universitaire » (date, heure, lieu + mini-carte, description, ajouter au calendrier, itinéraire, autres événements). ~1440×1100

## Lot F2 — Espace fidèle : démarches et compte (agent F2)
- WEB-FID-Notifications : liste groupée (Aujourd'hui / Cette semaine / Plus tôt), filtres (Toutes, Demandes, Messages, Paroisse), non lues marquées, « Tout marquer comme lu ». 1440×1000
- WEB-FID-Demandes : mes demandes : onglets En cours / Terminées, cartes-lignes (référence, type, paroisse du sacrement, statut, progression), bouton « Nouvelle demande », encadré « Comment ça marche ». 1440×1000
- WEB-FID-Demande-Suivi : JB-2026-00412 : statut, frise verticale des étapes datées, message de la paroisse, retrait (adresse, horaires du secrétariat, pièce d'identité), colonne droite : récapitulatif de la demande. 1440×1200
- WEB-FID-Pretres : prêtres joignables de Saint-Dominique (cartes : avatar initiales, office, sujets d'accompagnement, délai de réponse habituel, Écrire / Rendez-vous de confession), rappel confession en présentiel. 1440×1000
- WEB-FID-Confession-RDV : réservation : choix du prêtre (pilules), calendrier du mois (samedi 26 sélectionné), grille de créneaux de 10 min, lieu, récapitulatif à droite ; aucun champ de contenu, mention « aucun motif n'est demandé ». 1440×1100
- WEB-FID-Profil : profil et réglages en onglets (Compte, Paroisse suivie, Notifications, Apparence, Sécurité et appareils, Confidentialité) ; afficher l'onglet Compte + Sécurité (Face ID n/a web ; appareils connectés, clé de récupération du chiffrement, déconnexion partout) et un bloc « Supprimer mon compte ». ~1440×1400

## Lot R — Espace paroisse (agent R) — barre latérale paroisse de WEB-PAR-Tableau-de-bord
- WEB-PAR-Annonces : liste des annonces (onglets Publiées/Programmées/Brouillons, table-cartes avec catégorie, auteur, date, lectures, épinglée), bouton « Nouvelle annonce ». 1440×1100
- WEB-PAR-Annonce-Editeur : éditeur (titre, catégorie, texte riche simple avec barre d'outils, date de publication programmée, épingler, lieux concernés) + aperçu mobile à droite (carte telle que vue dans l'app). 1440×1300
- WEB-PAR-Horaires : horaires et lieux de culte : lieux (église Saint-Dominique, chapelle de la Cité universitaire), grille hebdomadaire des messes/confessions/adoration par jour, exception ponctuelle (dimanche 4 oct.), dialog « Ajouter un horaire » ouvert. 1440×1200
- WEB-PAR-Agenda : agenda du mois d'octobre 2026 (vue mois avec événements colorés sobrement), liste latérale du jour sélectionné, « Nouvel événement ». 1440×1100
- WEB-PAR-Messagerie : messagerie du prêtre (Abbé Ndiaye) : liste conversations (Sans réponse / Toutes), fil ouvert avec la note de confession, rappel déontologique ; aucune lecture par le secrétariat (mention). 1440×1000
- WEB-PAR-Confessions : créneaux de confession : semaine, grille prêtre × créneaux (réservé / libre / fermé), paramètres (durée 10 min, plage 16 h-18 h), « Ouvrir des créneaux » ; seuls prénom et heure visibles. 1440×1100
- WEB-PAR-Equipe : équipe et offices : table (personne, office, depuis, capacités clés, MFA), nomination en attente, dialog « Inviter un membre » ouvert. 1440×1100
- WEB-PAR-Parametres : paramètres de la paroisse : identité (nom, adresse, contacts, photo), registres tenus par la paroisse (types d'actes délivrés), délais de traitement, modèles de messages, visibilité publique ; sections en cartes avec « Enregistrer ». 1440×1300

## Lot D — Diocèse et plateforme (agent D) — barre latérale variante : sélecteur de contexte « Archidiocèse de Dakar · Espace diocèse » (Abbé Théodore Diatta, chancelier) ou « Plateforme · Numerisen » (Moustoifa Ben, admin)
- WEB-DIO-Tableau-de-bord : agrégats seulement (aucune donnée nominative) : déploiement (62 paroisses, 1 active, 4 en préparation) en liste de paroisses avec statut, demandes d'actes du mois par paroisse (agrégat), délais, un graphique sobre, prochaines nominations. 1440×1300
- WEB-DIO-Structure : arbre des juridictions (Province → Archidiocèse → doyennés → paroisses → CEB) à gauche, fiche du nœud sélectionné (doyenné Plateau-Médina) à droite, « Ajouter un nœud ». 1440×1100
- WEB-DIO-Nominations : nominations (table : personne, office, nœud, début, fin, statut) + import du mouvement annuel (zone de dépôt, aperçu de 8 lignes avec 1 erreur à corriger). 1440×1300
- WEB-DIO-Clerge : annuaire du clergé (filtres doyenné/office, table ou cartes, fiche latérale ouverte). 1440×1100
- WEB-PLA-Tableau-de-bord : plateforme : santé (1 diocèse, 5 paroisses paramétrées, 312 comptes, 14 staff, MFA 100 %), incidents, files techniques, en liste sobre + un graphique d'inscriptions. 1440×1100
- WEB-PLA-Referentiels : types de nœuds, catalogue d'offices, matrice des capacités (office × capacité, cases cochées) en onglets ; afficher la matrice. 1440×1300
- WEB-PLA-Comptes : comptes (Keycloak) : table, filtres rôle/MFA/statut, fiche latérale d'un compte (sessions, réinitialiser MFA). 1440×1100
- WEB-PLA-Audit : journal d'audit (horodatage, acteur, action, objet, nœud, IP masquée), filtres, détail JSON d'un événement en panneau. 1440×1100
