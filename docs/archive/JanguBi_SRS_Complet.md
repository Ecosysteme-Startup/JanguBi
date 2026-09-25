

**NUMERISEN**

*Services Numériques*

**Jangu Bi**

*"La Leçon"*

Plateforme Communautaire Catholique du Sénégal

**Spécification Complète des Fonctionnalités**

*Document interne — Version 1.0*

Mai 2025

# **1\. Résumé Exécutif**

Jangu Bi est une plateforme numérique dédiée à la communauté catholique du Sénégal. Elle réunit en un seul espace les fidèles, les prêtres, les diacres, les religieux, les évêques et les archevêques, avec des outils adaptés à leur vie quotidienne, leurs responsabilités pastorales et leurs besoins administratifs.

| *"Jàngu Bi" signifie "La Leçon" en wolof — une référence directe à la mission* d'enseignement et d'accompagnement spirituel au cœur de l'Église catholique. |
| :---- |

La plateforme est pensée selon un principe central : chaque utilisateur doit trouver dans Jangu Bi des outils si adaptés à son quotidien qu'il en devienne naturellement dépendant. Pour le prêtre, c'est l'outil qu'il consulte plusieurs fois par jour. Pour le fidèle, c'est l'application qu'il ouvre chaque matin.

## **Les 9 modules de la plateforme**

| Module | Ce que ça fait | Utilisateurs |
| ----- | ----- | :---: |
| **Liturgie & Prière** | Lectures du jour, Office divin (Liturgie des Heures), réflexion du curé | Tous |
| **Bible & Chapelet** | Bible complète, Lectio Divina, chapelet guidé et communautaire, intentions de prière | Tous |
| **Communication Pastorale** | Annuaire de disponibilités, messagerie sécurisée fidèle-clergé, inter-clergé | Tous |
| **Actualités** | Fil personnalisé par paroisse et diocèse — 3 formats de contenu | Tous |
| **Documents Officiels** | Demande, suivi, workflow de validation et coffre-fort numérique | Tous |
| **Agenda & Événements** | Calendrier liturgique automatique \+ événements pastoraux créés | Tous |
| **Intentions de Messe** | Demande de messe dédiée avec offrande via mobile money | Fidèles \+ Prêtres |
| **Dons & Quêtes** | Collectes paroissiales et diocésaines via Wave, Orange Money, Free Money | Tous |
| **Jangu Bi TV** | Messes en direct, homélies, catéchèse, formation exclusive clergé | Tous |

# **2\. Contexte et Opportunité**

## **La communauté catholique au Sénégal**

Bien que le Sénégal soit majoritairement musulman, sa communauté catholique est organisée, active et fortement ancrée dans la vie sociale et institutionnelle du pays. Elle compte environ 900 000 fidèles répartis dans sept diocèses (Dakar, Thiès, Saint-Louis, Ziguinchor, Tambacounda, Kaolack et Kolda), animés par des centaines de prêtres, diacres, religieuses et religieux.

## **Le vide numérique actuel**

Les paroisses communiquent via des groupes WhatsApp sans structure ni traçabilité. Les demandes de documents officiels se font en personne. Les prêtres ne disposent d'aucun tableau de bord pour gérer leur activité pastorale. Jangu Bi comble ce vide.

# **3\. Les Acteurs de la Plateforme**

## **3.1 Rôles pastoraux**

La hiérarchie pastorale définit le périmètre d'action et les fonctionnalités accessibles à chaque acteur.

| Acteur | Qui est-il ? | Périmètre | Ancre de rétention principale |
| ----- | ----- | ----- | ----- |
| **Fidèle** | Le catholique pratiquant. Suit sa paroisse, prie, fait ses démarches. | Sa paroisse \+ diocèse | Notification évangile quotidien \+ coffre-fort documents |
| **Religieux/se** | Membre d'un ordre (Franciscains, Dominicains…). Vie de prière intense et structurée. | Sa communauté \+ diocèse | Office divin complet — ouvre l'app 3 à 7 fois par jour |
| **Diacre** | Ministre ordonné assistant le prêtre dans la vie pastorale. | Sa paroisse | Liturgie des Heures \+ gestion administrative |
| **Prêtre / Curé** | Chef spirituel et pastoral de la paroisse. Célèbre les sacrements. | Sa paroisse | Office divin \+ dashboard pastoral \+ publication actus |
| **Évêque** | Responsable d'un diocèse. Ordonne, supervise, publie. | Son diocèse | Vue d'ensemble diocèse \+ lettres pastorales |
| **Archevêque** | Responsable d'une province ecclésiastique. | Sa province | Vue provinciale \+ communication évêques |

## **3.2 Rôles d'administration digitale de la plateforme**

En parallèle des rôles pastoraux, la plateforme dispose de rôles d'administration digitale. Ces deux dimensions coexistent et sont indépendantes : un prêtre peut aussi être administrateur digital de sa paroisse.

| Rôle admin | Périmètre | Responsabilités principales |
| ----- | ----- | ----- |
| **Super Admin** | Plateforme globale | Accès complet. Structure territoriale. Validation archevêques. Configuration système. Modération globale. |
| **Province Admin** | Province | Gestion digitale de la province. Support aux diocèses. |
| **Diocese Admin** | Diocèse | Gestion digitale du diocèse. Validation des paroisses. |
| **Parish Admin** | Paroisse | Gestion digitale de la paroisse. Peut être un laïc nommé. |

## **3.3 Le principe du périmètre territorial**

Tout contenu publié sur Jangu Bi est associé à un périmètre précis : Paroisse → Diocèse → Province → Global. Un fidèle ne voit que ce qui concerne sa communauté. Un évêque ne peut publier que pour son diocèse. Ce principe garantit la pertinence de chaque information et respecte la structure de l'Église.

# **4\. Le Super Administrateur**

Le Super Administrateur est l'acteur technique le plus élevé de la plateforme. Il n'a pas de rôle pastoral — il est le garant de l'intégrité, de la structure et du bon fonctionnement de Jangu Bi dans son ensemble.

## **4.1 Ce que le Super Admin peut faire**

| Domaine | Actions disponibles |
| ----- | ----- |
| **Structure territoriale** | Créer, modifier, désactiver des Provinces, Diocèses, Paroisses et Communautés religieuses. |
| **Comptes clergé** | Créer et valider les comptes Archevêque. Peut intervenir sur n'importe quel compte en cas de problème. |
| **Table de référence des dons** | Gérer les types de dons système (Quête dominicale, Denier de l'Église, Don libre, etc.). |
| **Contenu global** | Publier des actus et vidéos à portée GLOBAL. Gérer la catégorie Formation sur Jangu Bi TV. |
| **Modération** | Dépublier tout contenu sur la plateforme. Signaler des comptes. Gérer les abus. |
| **Configuration système** | Paramètres globaux : délai de purge des messages, SLA des documents, règles de notification. |
| **Gestion des utilisateurs** | Activer / désactiver n'importe quel compte. Réinitialiser des mots de passe. |
| **Analytics globales** | Accès à toutes les métriques d'usage de la plateforme. |

## **4.2 Tableau de bord Super Admin**

Le dashboard Super Admin offre une vue en temps réel de la santé de la plateforme, organisée en quatre blocs.

| Bloc | Indicateurs affichés |
| ----- | ----- |
| **Santé plateforme** | Utilisateurs actifs (J, J-7, J-30). Taux de rétention. Couverture géographique (paroisses actives / total). |
| **File de validation** | Comptes clergé en attente de validation. Demandes de rôle pastoral non traitées. Transferts paroissiaux bloqués. |
| **Contenu & Modération** | Signalements non traités. Contenus publiés aujourd'hui par portée. Catégorie Formation : vidéos publiées ce mois. |
| **Finance & Dons** | Volume total des transactions (Wave, OM, Free Money). Taux de succès des paiements. Campagnes actives. |

| Le Super Admin ne reçoit aucune notification pastorale et n'a pas accès aux conversations entre fidèles et clergé — même en tant qu'administrateur. La confidentialité pastorale est non négociable. |
| :---- |

# **5\. Onboarding & Gestion des Comptes**

## **5.1 Parcours d'inscription — Fidèle**

Après son inscription, le fidèle doit obligatoirement sélectionner une paroisse principale avant d'accéder à l'application. Il peut ensuite suivre d'autres paroisses de son choix, sans limite. Trois méthodes de recherche : géolocalisation, recherche textuelle, navigation Diocèse → Paroisses.

La paroisse principale détermine où ses demandes de documents sont envoyées et quel contenu il voit en priorité. Son changement suit un workflow officiel de transfert paroissial.

## **5.2 Création des comptes clergé — Chaîne de validation descendante**

| Qui valide | Qui est créé / validé | Mode |
| ----- | ----- | ----- |
| **Super Admin** | Archevêque | Invitation ou auto-déclaration |
| **Archevêque** | Évêque | Invitation ou auto-déclaration |
| **Évêque** | Prêtre (assigné à une paroisse) | Invitation ou auto-déclaration |
| **Prêtre** | Diacre, Religieux/se | Invitation ou auto-déclaration |

## **5.3 Assistants & Délégation**

Un prêtre ou un évêque peut désigner un assistant (diacre ou collaborateur laïc) qui gère en son nom certaines tâches administratives : traitement des demandes de documents, publication d'annonces, gestion du calendrier. L'assistant n'a jamais accès aux conversations pastorales confidentielles et ne peut pas signer de documents officiels.

# **6\. Les Fonctionnalités — Détail**

## **6.1 Liturgie & Prière Quotidienne**

Le module le plus stratégique : il crée le motif de revenir plusieurs fois par jour pour tout le clergé et les religieux.

### **Lectures de la messe (API AELF)**

Fetch quotidien des lectures liturgiques (Première Lecture, Psaume, Évangile). Visible par tous les utilisateurs.

### **Liturgie des Heures — Office Divin**

7 heures de prière quotidienne disponibles : Laudes, Tierce, Sexte, None, Vêpres, Complies, Office des lectures (Matines). L'app détecte l'heure locale et met en avant l'Heure en cours. Accessible au clergé et aux religieux.

### **Réflexion Pastorale**

Le prêtre publie une pensée courte (500 caractères max) liée aux lectures du jour. Visible par les fidèles de sa paroisse sous les lectures. L'évêque publie pour son diocèse, l'archevêque pour sa province.

## **6.2 Bible & Chapelet**

### **Bible — Mode Prière et Mode Lectio Divina**

Mode Prière : lecture verset par verset, favoris, recherche sémantique. Mode Lectio Divina : quatre étapes (Lectio → Meditatio → Oratio → Contemplatio) avec timer et zone de notes privées. Les prêtres et diacres disposent d'un espace de notes d'homélie directement sur chaque passage.

Les prêtres peuvent créer des parcours de lecture thématiques (30 jours, Carême, Avent…) et les partager avec leurs paroissiens.

### **Chapelet**

Les mystères sont sélectionnés automatiquement selon le jour liturgique. Chapelet communautaire : un prêtre ou un religieux initie une session, les participants suivent en temps réel. Intentions de prière : les fidèles soumettent des intentions, le prêtre les intègre dans le chapelet paroissial.

## **6.3 Communication Pastorale — Allo-Prêtre & Messagerie**

### **Allo-Prêtre — Couche de découverte**

Annuaire des ministres par paroisse avec disponibilités en temps réel : chat pastoral ouvert/fermé, horaires de confession, disponibilité pour visites. Statut spécial "En retraite spirituelle" affiché automatiquement.

### **Messagerie — Types de conversations**

Le fidèle choisit un type à l'initiation : question simple (sous 48h), accompagnement suivi, ou urgence. Le prêtre voit les conversations classées par priorité dans son dashboard. Toutes les conversations sont chiffrées bout-en-bout (Fernet). Auto-purge configurée par le Super Admin.

### **Communication inter-clergé**

Canal distinct du pastoral : archevêque → tous ses évêques, évêque → tous ses prêtres, prêtre → ses diacres et confrères. Équivalent d'un outil de communication interne pour l'Église.

## **6.4 Actualités — 3 Formats de Contenu**

| Format | Description | Qui publie | Portée max |
| ----- | ----- | ----- | ----- |
| **Annonce** | Message court (300 caractères max) pour info pratique immédiate | Prêtre, Diacre | Paroisse |
| **Article** | Contenu long — catéchèse, témoignage, réflexion de fond | Prêtre, Évêque | Diocèse |
| **Lettre Pastorale** | Document officiel formel de l'Évêque ou de l'Archevêque | Évêque, Archevêque | Province |

Les diacres rédigent des brouillons soumis au prêtre pour validation avant publication. Les évêques peuvent "booster" un article paroissial à l'échelle diocésaine. Les réactions (prier, amen, participer) remplacent les commentaires libres pour éviter les débats.

## **6.5 Documents Officiels & Coffre-Fort Numérique**

8 types de documents couverts : certificats de baptême, communion, confirmation, mariage, sépulture, lettre de recommandation, lettre de transfert paroissial, acte d'ordination.

### **Workflow à 3 niveaux**

* Niveau 1 — Diacre / Parish Admin : reçoit, vérifie les registres, prépare le document.

* Niveau 2 — Prêtre : valide et signe numériquement.

* Niveau 3 — Évêque : pour les documents diocésains (ordinations, confirmations).

### **Coffre-fort numérique**

Tout document émis via Jangu Bi est automatiquement stocké dans l'espace personnel du fidèle — accessible à vie. C'est le levier de rétention le plus fort du module : un fidèle qui y conserve ses documents ne désinstalle jamais l'application.

### **Transfert paroissial**

Workflow inter-paroissial : le prêtre de la paroisse d'origine valide et émet la lettre, transmise via l'app au prêtre de la paroisse cible. À la réception confirmée, le rattachement paroissial du fidèle est mis à jour automatiquement.

### **SLA et escalade automatique**

Délais définis par type de document (3 à 10 jours). En cas de dépassement, escalade automatique au niveau supérieur avec notification.

## **6.6 Agenda & Événements**

Deux dimensions : le calendrier liturgique automatique (Avent, Carême, Pâques, fêtes des saints — calculé depuis les données AELF, aucune saisie requise) et les événements pastoraux créés par le clergé (retraites, pèlerinages, ordinations, confirmations).

Chaque événement créé génère automatiquement une annonce dans les Actus. Si un live TV est associé, la notification est envoyée 15 minutes avant le début. Les fidèles peuvent s'inscrire aux événements avec liste de participants accessible au créateur.

## **6.7 Intentions de Messe**

Un fidèle soumet une intention (type, bénéficiaire, date souhaitée, offrande optionnelle). Le prêtre accepte ou propose une autre date. Le fidèle confirme. Le prêtre marque la messe comme célébrée — le fidèle reçoit une confirmation et un reçu numérique.

4 types d'intentions : pour un défunt, pour un vivant, pour une occasion spéciale, pour une communauté. L'offrande est un type de don dans la table de référence — traité via mobile money.

| L'offrande n'est jamais obligatoire. C'est une tradition, pas une condition. Une intention sans offrande est tout aussi valide et traitée avec le même soin. |
| :---- |

## **6.8 Dons & Quêtes**

### **Table de référence des types de dons (gérée par Super Admin)**

| Type | Bénéficiaire | Récurrence | Qui active |
| ----- | ----- | :---: | ----- |
| **Quête dominicale** | Paroisse | Hebdomadaire | Prêtre |
| **Denier de l'Église** | Diocèse | Annuel | Évêque (fixe la période) |
| **Intention de messe** | Paroisse / Prêtre | À la demande | Automatique (module intentions) |
| **Projet spécial** | Paroisse ou Diocèse | Campagne | Prêtre ou Évêque |
| **Don libre** | Au choix | À la demande | Toujours disponible |

Méthodes de paiement (Sénégal-first) : Wave (priorité 1), Orange Money (priorité 2), Free Money (priorité 3). Chaque donateur reçoit un reçu numérique. Chaque prêtre et évêque voit en temps réel l'état des collectes de sa communauté.

## **6.9 Jangu Bi TV**

Catalogue vidéo alimenté depuis YouTube, organisé en 6 catégories : Messes, Homélies, Catéchèse, Événements, Témoignages (validés avant publication), Formation (réservée exclusivement au clergé).

Les prêtres publient leurs homélies, planifient des lives (messe, vêpres, chapelet) et voient les statistiques de visionnage. Une notification est envoyée aux fidèles de la paroisse 15 minutes avant un live. La catégorie Formation est le levier de rétention le plus fort pour le clergé sur ce module.

# **7\. Tableaux de Bord par Rôle**

## **Fidèle**

| Bloc | Contenu |
| ----- | ----- |
| **Liturgie** | Évangile du jour \+ réflexion du curé |
| **Documents** | Demandes en cours \+ statut en temps réel |
| **Actualités** | 3 dernières actus de sa paroisse |
| **Événements** | Prochains événements de sa paroisse et diocèse |

## **Prêtre**

| Bloc | Contenu |
| ----- | ----- |
| **Urgent** | Documents en attente de signature \+ conversations urgentes \+ intentions de messe en attente |
| **À traiter** | Documents en vérification \+ conversations pastorales ouvertes (compteurs) |
| **Liturgie** | Prochaine Heure de l'Office \+ lectures de la semaine à venir |
| **Paroisse** | Fidèles actifs cette semaine \+ dernière actus publiée \+ prochains événements |

## **Évêque**

| Bloc | Contenu |
| ----- | ----- |
| **Alertes** | Documents en retard d'escalade \+ prêtres inactifs depuis \> 30 jours |
| **Diocèse** | Prêtres actifs / total \+ documents traités cette semaine \+ fidèles connectés |
| **Communication** | Messages inter-clergé non lus \+ dernière lettre pastorale et engagement |
| **Liturgie** | Prochaine Heure de l'Office |

## **Archevêque**

| Bloc | Contenu |
| ----- | ----- |
| **Province** | Vue par diocèse : évêque \+ dernier contact \+ activité globale (fidèles, documents, dons) |
| **Communication** | Messages avec évêques non lus \+ dernière publication provinciale |
| **Liturgie** | Prochaine Heure de l'Office |

## **Super Admin**

| Bloc | Contenu |
| ----- | ----- |
| **Santé plateforme** | Utilisateurs actifs J/J-7/J-30. Taux de rétention. Paroisses actives / total. |
| **File de validation** | Comptes clergé en attente. Demandes de rôle non traitées. Transferts paroissiaux bloqués. |
| **Modération** | Signalements non traités. Contenus publiés par portée. Vidéos Formation publiées ce mois. |
| **Finance** | Volume transactions par provider (Wave, OM, Free Money). Taux de succès. Campagnes actives. |

# **8\. Système de Notifications**

## **8.1 Règles globales non négociables**

* Silence nocturne : aucune notification push entre 22h et 6h (sauf urgence acceptée par l'utilisateur).

* Anti-flood : jamais deux notifications du même type en moins de 2 heures.

* App ouverte récemment : si l'app a été ouverte dans la dernière heure → badge uniquement, pas de push.

* Plafond journalier : maximum 5 notifications push par jour, tous types confondus.

## **8.2 Paramètres par défaut**

| Type | Fidèle | Religieux | Diacre | Prêtre | Évêque | Archevêque |
| ----- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Liturgique** | Push | Push | Push | Push | Push | Push |
| **Pastoral** | Push | Push | Push | Push | Silencieux | Silencieux |
| **Éditorial** | Silencieux | Silencieux | Silencieux | Push | Push | Push |
| **Documents** | Push | — | Push | Push | Silencieux | Silencieux |
| **Événements** | Silencieux | Silencieux | Push | Push | Push | Push |
| **Dons** | Silencieux | — | — | Push | Push | Push |
| **Système** | Push | Push | Push | Push | Push | Push |

## **8.3 Statut spécial clergé**

Un prêtre peut activer un mode "En retraite spirituelle" avec date de fin. Toutes les notifications sont suspendues sauf le type Système. Son profil Allo-Prêtre affiche automatiquement l'indisponibilité. Les messages pastoraux reçoivent une réponse automatique d'indisponibilité.

# **9\. Priorités de Développement**

| Priorité | Module / Feature | Raison |
| :---: | ----- | ----- |
| **P1 🔴** | **Modèle User → Paroisse → Diocèse** | Prérequis bloquant de tout le système de scoping |
| **P1 🔴** | **Liturgie des Heures (AELF)** | Usage quotidien garanti pour tout le clergé |
| **P2 🔴** | **Allo-Prêtre \+ Messagerie unifiés** | Cœur relationnel fidèle ↔ clergé |
| **P2 🔴** | **Actus — interface publication \+ 3 types** | Remplace les groupes WhatsApp des prêtres |
| **P2 🔴** | **Comptes clergé — chaîne de validation** | Sans ça, pas de clergé sur la plateforme |
| **P3 🟡** | **Documents — coffre-fort \+ 3 niveaux \+ transfert** | Rétention fidèle forte, utilité quotidienne paroisse |
| **P3 🟡** | **Réflexion pastorale** | Lien curé ↔ fidèle quotidien |
| **P4 🟡** | **Bible — Lectio Divina** | Rétention clergé et religieux |
| **P4 🟡** | **Agenda & Événements** | Utilité paroissiale hebdomadaire |
| **P4 🟡** | **Intentions de Messe** | Pastoral \+ contribution financière |
| **P5 🟢** | **Dons (Wave, OM, Free Money)** | Haute valeur long terme, intégration complexe |
| **P5 🟢** | **Chapelet communautaire \+ intentions** | Dimension communautaire différenciante |
| **P6 🟢** | **Jangu Bi TV — publication clergé \+ Formation** | Valeur éditoriale et formation continue |

# **10\. Conclusion**

Jangu Bi est une réponse concrète, structurée et ambitieuse à un vide numérique réel au sein de la communauté catholique du Sénégal. La plateforme ne cherche pas à remplacer la vie de l'Église — elle cherche à la soutenir, la fluidifier et la rendre plus accessible dans le monde d'aujourd'hui.

Chaque fonctionnalité est pensée depuis les besoins réels : le prêtre qui prépare son homélie chaque semaine, le fidèle qui cherche son certificat de baptême, l'évêque qui veut rejoindre tous ses prêtres d'un seul message, le diacre qui gère les demandes administratives de sa paroisse. Jangu Bi n'est pas une application générique adaptée à l'Église — c'est une plateforme construite pour l'Église, de l'intérieur.

| Jangu Bi ambitionne de devenir la plateforme de référence de la communauté catholique en Afrique de l'Ouest francophone — un espace numérique à l'image de la foi qu'il sert : structuré, communautaire, digne et profondément ancré dans le quotidien. |
| :---- |

*Document préparé par NUMERISEN — Services Numériques*

Confidentiel — Mai 2025