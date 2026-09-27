# Brief : maquettes complètes Jàngu Bi V1 (présentation au Directeur général)

## 1. Enjeu
Ces maquettes seront présentées au DG. Elles doivent paraître **conçues par un studio de design sérieux** : cohérentes, réalistes, denses en vrai contenu, sans aucun effet « généré par IA ». Chaque écran doit pouvoir être pris pour une capture d'un produit en production.

## 2. Produit (rappel)
Jàngu Bi (« La Leçon » en wolof) est une application web pour les fidèles catholiques du Sénégal (≈ 924 000 catholiques, 7 diocèses, 172 paroisses). Éditeur : Numerisen. La copie est en français (quelques mots de wolof possibles : « Jàmm ak jàmm », « Dalal ak jàmm »).

**Côté fidèle** :
1. **La Parole du jour** : lectures, Bible, chapelet.
2. **Ma paroisse** : annonces du dimanche, horaires, événements.
3. **Mes demandes d'actes** : extrait de baptême, de confirmation ou de mariage, demandé à la **paroisse du sacrement** et suivi en ligne. L'acte reste un **original papier signé et scellé, à retirer**, jamais un PDF.
4. **Parler à un prêtre** : messagerie chiffrée de bout en bout avec les prêtres joignables, et **rendez-vous de confession en présentiel**. Ne jamais suggérer une confession par message : un bandeau le rappelle toujours.

**Espace paroisse** (secrétariat, curé, prêtres) : annonces, horaires et lieux de culte, agenda, file des demandes d'actes, messagerie prêtre, créneaux de confession, équipe et nominations, tableau de bord.

**Espace diocèse** (évêque, chancelier, délégué) : tableau de bord agrégé, structure (arbre des juridictions), nominations (dont l'import du mouvement annuel), annuaire du clergé.

**Espace plateforme** (Numerisen) : tableau de bord, référentiels (types de nœuds, catalogue d'offices, matrice des capacités), comptes (Keycloak), journal d'audit.

**Authentification** : Keycloak. Les écrans de connexion sont une page Keycloak habillée aux couleurs de Jàngu Bi. La double authentification (MFA) est obligatoire pour le staff.

**Hiérarchie** : arbre paramétrable Province → Diocèse → (Zone) → (Doyenné) → Paroisse / Quasi-paroisse / Aumônerie → CEB. Les **offices** (curé, vicaire, doyen, chancelier, secrétaire, référent, catéchiste, responsable de CEB) sont nommés, datés, et donnent des **capacités** sur un nœud et son sous-arbre.

## 3. Direction artistique : « Lumière », en BLEU
Choix du propriétaire : **le bleu est la couleur principale.** On garde l'esprit du territoire A « Lumière » :
- la Parole traitée comme un objet précieux ;
- un fond papier chaud ;
- une grande typographie éditoriale ;
- des filets fins, une numérotation éditoriale ;
- le **bandeau liturgique** en tête de journal (date, temps liturgique, pastille de couleur liturgique, références).

L'ancien accent vert devient un **bleu marial profond**. Les références d'esprit sont functionhealth.com (premium, aéré, données mises en scène) et une revue éditoriale (type Monocle).

La source de vérité visuelle est `DESIGN-SYSTEM.md` et les gabarits de `templates/`, produits par l'agent design system. Tout écran doit les suivre à la lettre : mêmes tokens, mêmes composants, mêmes shells.

## 4. Interdits (signatures « IA »)
- **Polices** : Inter, Roboto, Arial, Fraunces, Poppins, Montserrat, Space Grotesk.
- **Effets** : dégradés « wash » de fond, dégradés violet-bleu, cartes à bordure gauche colorée, emoji, icônes dans des ronds pastel.
- **Mises en page toutes faites** : grilles de 4 tuiles d'actions identiques, rangées de 3 ou 4 « stat cards » génériques avec une icône, badges multicolores partout, ombres lourdes.
- **Clichés** : wax, soleil couchant, baobab.
- **Contenus** : lorem ipsum, microcopie générique (« Bienvenue sur votre tableau de bord ! »), chiffres ronds suspects.
- **Images** : aucune image générée. Pas de photo disponible (réseau bloqué) : voir §7.

## 5. Données réalistes (à réutiliser partout, de façon cohérente)
- **Date du jour** : jeudi 24 septembre 2026, jeudi de la 25e semaine du temps ordinaire (année paire, cycle A pour les dimanches), couleur liturgique **verte**.
- **Lectures du jour** : Ecclésiaste 1, 2-11 ; Psaume 89 (90), 3-6, 12-14.17 ; Luc 9, 7-9. **Textes autorisés** : traduction Segond 1910, domaine public (ne pas inventer d'autres versets longs).
  - Ec 1, 2 : « Vanité des vanités, dit l'Ecclésiaste, vanité des vanités, tout est vanité. »
  - Ec 1, 4 : « Une génération s'en va, une autre vient, et la terre subsiste toujours. »
  - Ec 1, 9 : « Ce qui a été, c'est ce qui sera, et ce qui s'est fait, c'est ce qui se fera, il n'y a rien de nouveau sous le soleil. »
  - Ps 90, 12 : « Enseigne-nous à bien compter nos jours, afin que nous appliquions notre cœur à la sagesse. »
  - Ps 90, 14 : « Rassasie-nous chaque matin de ta bonté, et nous serons toute notre vie dans la joie et l'allégresse. »
  - Lc 9, 7-9 : « Hérode le tétrarque entendit parler de tout ce qui se passait, et il ne savait que penser. Car les uns disaient que Jean était ressuscité des morts ; d'autres, qu'Élie était apparu ; et d'autres, qu'un des anciens prophètes était ressuscité. Mais Hérode dit : J'ai fait décapiter Jean ; qui donc est celui-ci, dont j'entends dire de telles choses ? Et il cherchait à le voir. »
- **Dimanche 27 septembre 2026** : 26e dimanche du temps ordinaire (A).
- **Juridictions** :
  - Province de Dakar ;
  - Archidiocèse de Dakar (Archevêque : Mgr André Guèye) ;
  - diocèses de Thiès, Saint-Louis, Kaolack, Ziguinchor, Tambacounda, Kolda ;
  - doyennés de Dakar : Plateau-Médina, Grand Dakar-Yoff, Niayes, Sine, Petite-Côte.
- **Paroisses** (Archidiocèse de Dakar) :
  - Paroisse Saint-Dominique (paroisse universitaire, Point E, doyenné Plateau-Médina), **paroisse pilote**, avec 2 lieux de culte : église Saint-Dominique et chapelle de la Cité universitaire ;
  - Cathédrale Notre-Dame-des-Victoires (Plateau) ;
  - Saint-Pierre des Baobabs ;
  - Sainte-Thérèse de Grand-Dakar ;
  - Notre-Dame des Anges de Ouakam ;
  - Saint-Joseph de Médina.
- **Personnes fictives** :
  - fidèles : Marie-Thérèse Diouf (utilisatrice de référence, 34 ans, paroisse suivie Saint-Dominique, baptisée à Sainte-Thérèse de Grand-Dakar), Jean-Baptiste Sène, Awa Faye, Pierre Ndour, Élisabeth Gomis, Joseph Mendy, Anna Sarr, Paul Diatta, Michel Badji, Thérèse Ndione, Cécile Coly, Albert Senghor ;
  - clergé de Saint-Dominique : Abbé Augustin Ndiaye (curé), Père Emmanuel Tine (vicaire), Abbé Robert Sagna (vicaire) ;
  - secrétaire paroissiale : Mme Germaine Faye ;
  - référent numérique : Lucien Mendy ;
  - chancelier de l'archidiocèse : Abbé Théodore Diatta ;
  - admin Numerisen : Moustoifa Ben.
- **Horaires Saint-Dominique** : dimanche 7 h 30, 9 h 30 (messe des étudiants), 11 h 30, 18 h 30 ; en semaine 7 h et 18 h 30 ; samedi confessions 16 h-18 h, messe anticipée 18 h 30.
- **Annonces** :
  - Quête impérée pour le Grand Séminaire de Brin, ce dimanche ;
  - Inscriptions au catéchisme 2026-2027 jusqu'au 11 octobre ;
  - Messe d'action de grâce pour la rentrée universitaire, dimanche 4 octobre à 9 h 30 ;
  - Répétition de la chorale Sainte-Cécile, samedi 16 h ;
  - Préparation du pèlerinage à Popenguine ;
  - Journée de récollection des CEB, samedi 10 octobre.
- **Demandes d'actes** :
  - statuts : Soumise · En vérification · Complément demandé · Prête à retirer · Retirée · Rejetée ;
  - références JB-2026-00398 à JB-2026-00421 ;
  - types : extrait d'acte de baptême (le plus fréquent, souvent « pour mariage »), attestation de confirmation, attestation de mariage religieux, certificat de première communion, attestation de parrain/marraine.
- **Tableau de bord de la paroisse pilote** (données modestes et plausibles) :
  - 214 fidèles rattachés, 131 actifs cette semaine ;
  - 3 annonces publiées cette semaine, 1 480 lectures ;
  - 17 demandes d'actes ce mois, délai moyen 4,2 jours, 2 en retard ;
  - 9 conversations ouvertes, première réponse en 5 h (médiane) ;
  - 12 rendez-vous de confession pris pour samedi.
- **Diocèse de Dakar** : 62 paroisses, dont 1 active sur Jàngu Bi (pilote) et 4 en préparation.
- **Plateforme** : 1 diocèse, 5 paroisses paramétrées, 312 comptes, 14 comptes staff (MFA 100 %).

## 6. Format technique OBLIGATOIRE (.dc.html)
Chaque écran est UN fichier `project/<NOM>.dc.html` autonome :

```html
<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Nom court de l'écran</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=...&display=swap" rel="stylesheet">
<style>
body{margin:0;background:#...;font-family:...}
a{color:#...;text-decoration:none}a:hover{color:#...}
</style>
</helmet>
<div style="width: 1440px; height: 1100px; box-sizing: border-box; ...">
  ...
</div>
</x-dc>
<script type="text/x-dc" data-dc-script data-props='{"$preview":{"width":1440,"height":1100}}'>
class Component extends DCLogic {
renderVals() { return {}; }
}
</script>
</body>
</html>
```

Règles (chacune échoue EN SILENCE si elle n'est pas respectée) :
- La ligne `<script src="./support.js"></script>` est gardée EXACTEMENT.
- Tous les éléments non vides sont fermés, tous les attributs sont entre guillemets.
- La racine a une taille FIXE (px) égale à celle de l'artboard. `$preview` porte la même taille. Une hauteur trop grande vaut mieux qu'un contenu coupé : ajuster la hauteur au contenu.
- Styles INLINE. `<helmet><style>` ne sert qu'aux bases (body, a, a:hover, :hover de boutons, :focus-visible, @keyframes). Aucune autre ressource externe que Google Fonts `css2`.
- Mise en page en flex ou grid avec `gap`. Grille : `display: grid; grid-template-columns: repeat(N, minmax(0, 1fr)); gap: …`.
- `{{hole}}` n'est qu'une lookup dans `renderVals()`, jamais une expression. Écrire le texte EN DUR.
- Toujours le bloc `<script type="text/x-dc" data-dc-script …>` avec `class Component extends DCLogic`, en JS classique.
- Pas d'innerHTML, pas d'`<iframe>`, `<object>` ni `<embed>`, pas d'image externe, pas d'emoji. Icônes en SVG inline stroke `currentColor` (jeu d'icônes du design system).
- **Navigation entre écrans** (prototype cliquable) : `<a href="AUTRE.dc.html">` vers le fichier cible, nom exact de la liste §8. Le `<a>` lui-même est stylé en bouton (pas de `<button>` dans un `<a>`). Les liens sans cible : `href="#"`.
- **Accessibilité** : `<button>`, `<a>`, `<input>`/`<select>`/`<textarea>` avec `<label>`. `aria-label` sur les boutons icône. Contraste ≥ 4,5:1. Cibles ≥ 44 px sur mobile. Pas de fausse barre de statut de téléphone.
- `lang="fr"`.

## 7. Images
Le réseau vers les banques d'images est bloqué. On n'utilise donc **aucune photo**, mais des **emplacements photo art-dirigés**, définis dans le design system : un cadre au ratio fixe, un fond bleu très pâle, une composition graphique abstraite en SVG inline (lumière traversant un vitrail, arc en plein cintre, rayons) et une légende en mono du type « PHOTO · Sortie de la messe de 9 h 30, Saint-Dominique ». Chaque emplacement porte un attribut `data-photo-slot="nom-du-slot"` pour être remplacé plus tard par de vraies photos. Pas de hachures grossières.

## 8. Écrans (noms de fichiers EXACTS, tailles)
**Design system**
- DS-Fondations.dc.html 1440×1800
- DS-Composants.dc.html 1440×2000

**Public**
- Main.dc.html (page d'accueil publique complète) 1440×3200
- PUB-Paroisses.dc.html (annuaire + carte schématique + recherche et filtres) 1440×1100
- PUB-Fiche-Paroisse.dc.html (fiche publique Saint-Dominique) 1440×1700
- PUB-Parole-du-jour.dc.html 1440×1600
- PUB-Pour-les-paroisses.dc.html (offre aux paroisses et diocèses, déroulé du pilote, formulaire de contact) 1440×2000
- PUB-Connexion.dc.html (Keycloak habillé) 1440×900
- PUB-Inscription-Compte.dc.html (étape 1/3) 1440×900
- PUB-Inscription-Paroisse.dc.html (étape 2/3 choix de paroisse + étape 3/3 consentement visible en récapitulatif) 1440×1000

**Espace fidèle, desktop** (shell fidèle)
- FID-Accueil 1440×1200 ; FID-Parole 1440×1700 ; FID-Bible 1440×1000 ; FID-Chapelet 1440×1000
- FID-Ma-Paroisse 1440×1400 ; FID-Annonce 1440×1600 ; FID-Evenement 1440×1100 ; FID-Notifications 1440×1000
- FID-Demandes 1440×1000 ; FID-Demande-Nouvelle 1440×1400 ; FID-Demande-Suivi 1440×1100
- FID-Pretres 1440×1000 ; FID-Conversation 1440×1000 ; FID-Confession-RDV 1440×1100 ; FID-Profil 1440×1400

**Mobile** (390 de large)
- MOB-Accueil 390×1100 ; MOB-Parole 390×1200 ; MOB-Ma-Paroisse 390×1100 ; MOB-Demande-Nouvelle 390×1100
- MOB-Demande-Suivi 390×900 ; MOB-Conversation 390×844 ; MOB-Confession 390×900 ; MOB-Menu 390×844

**Espace paroisse** (shell back-office)
- PAR-Tableau-de-bord 1440×1200 ; PAR-Annonces 1440×1000 ; PAR-Annonce-Editeur 1440×1300
- PAR-Horaires 1440×1100 ; PAR-Agenda 1440×1000 ; PAR-Parametres 1440×1200
- PAR-Demandes 1440×1000 ; PAR-Demande-Detail 1440×1200 ; PAR-Messagerie 1440×1000
- PAR-Confessions 1440×1000 ; PAR-Equipe 1440×1100

**Diocèse et plateforme** (shell back-office, contexte différent)
- DIO-Tableau-de-bord 1440×1200 ; DIO-Structure 1440×1100 ; DIO-Nominations 1440×1200 ; DIO-Clerge 1440×1000
- PLA-Tableau-de-bord 1440×1000 ; PLA-Referentiels 1440×1300 ; PLA-Comptes 1440×1000 ; PLA-Audit 1440×1000

Tous les fichiers portent le suffixe `.dc.html` (par exemple `FID-Accueil.dc.html`).

## 9. Qualité : principes de design (frontend-design / frontend-patterns)
- **Hiérarchie claire par écran** : un titre, une action principale, le reste en retrait. Pas de murs de cartes.
- **Densité honnête** : les écrans de travail montrent de vraies listes (8 à 15 lignes), des filtres, des états (vide, en retard, sélectionné), une pagination.
- **Formulaires complets** : labels, aides, champs requis marqués, validation inline (au moins un champ en erreur ou validé visible), étapes (stepper), récapitulatif.
- **États** : au moins un écran par zone montre un état particulier (vide, succès, alerte, hors-ligne, confirmation modale).
- **Micro-copie juste**, ecclésialement correcte (« paroisse du sacrement », « extrait d'acte de baptême », « rendez-vous de confession »), jamais marketing creux.
- **Cohérence** absolue avec le design system : tokens, rayons, espacements, icônes, shells.
- **Lisibilité** : corps 15-16 px minimum sur desktop, 16 px sur mobile ; aînés et plein soleil.
