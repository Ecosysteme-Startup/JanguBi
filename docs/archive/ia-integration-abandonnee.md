> **Obsolète — archivé.** L'app `rag` a été supprimée (ADR-016) et la plateforme n'embarque aucune IA (ADR-018,
> `docs/v1/03-DECISIONS-ADR.md`). Ce document décrit un état abandonné ; il est gardé pour l'historique.

# Intégration de l'Intelligence Artificielle (JanguBi)

Ce document explique aux équipes métier, marketing et développeurs pourquoi et comment nous avons injecté l'Intelligence Artificielle de Google (Gemini) dans le cœur de JanguBi.

---

## 🚀 1. Le Besoin Initial & Les Avantages de l'IA
Historiquement, la recherche textuelle simple (ex: via PostgreSQL) n'est efficace que si l'utilisateur connaît les mots exacts ("Ne crains pas"). Or, la spiritualité et le besoin d'accompagnement s'expriment souvent de manière floue, sous forme de sentiments ou de concepts ("J'ai peur du futur", "Je me sens seul", "Pardonner aux autres").

**Les Avantages de notre système (RAG - Retrieval Augmented Generation) :**
1. **Compréhension Sémantique** : L'IA ne cherche plus la chaîne de caractère exacte, mais traduit l'émotion de l'utilisateur en concept, et va fouiller la base via la vectorisation.
2. **Langage Naturel** : Au lieu de cliquer sur 5 filtres (Date = Demain, Service = Confession, Ville = Dakar), l'utilisateur écrit ou dicte : *"Y a-t-il un prêtre dispo à Dakar demain après-midi pour me confesser ?"*.
3. **Assistance 24/7 Multi-Domaines** : Un seul point d'entrée central au niveau fonctionnel. L'IA comprend instantanément si l'utilisateur veut prier (Rosaire), lire (Bible) ou s'entretenir physiquement (Disponibilité) et route ses actions.
4. **Zéro Hallucination** : Grâce au procédé RAG (Le Backend extrait la donnée SQL et la fournit à l'IA avec consigne stricte de lire ce contexte), l'IA ne générera jamais un verset biblique imaginaire.

---

## 🏗️ 2. Architecture du RAG Intelligent dans JanguBi
Le secret derrière la rapidité et la fiabilité de JanguBi réside dans l'approche à 2 passages (Agentique/Routing).

1. **Passage 1 (Flash)** : On donne la phrase utilisateur à l'IA avec un ordre strict (JSON). L'IA nous renvoie sa compréhension mathématisée :
    *   `Intent: AVAILABILITY`
    *   `Date: 2026-03-05`
    *   `Service: confession`
2. **Lookup Django** : Nos algorithmes ultra-rapides en Python (non pilotés par l'IA) parcourent la base SQL, calculent les plannings du 2026-03-05 et trouvent que le Père Koffi est libre de 14h à 17h.
3. **Passage 2 (Génération)** : On redonne tout à l'IA en mode "Traduction" : « L'utilisateur avait demandé ça. Le système SQL lui répond : [Père Koffi dispo Jeudi de 14h-17h]. Formule ta réponse humaine ! ».

---

## 🧪 3. Prompts & Scénarios de Test pour la Démo

Voici la meilleure manière de faire une démonstration de la puissance du système. Copiez-collez les requêtes suivantes dans l'interface de JanguBi (ou via commande `curl`) pour prouver les différents fonctionnements.

### Cas d'Usage A : La Sémantique Biblique (PgVector / Embeddings)
L'objectif est de prouver que l'IA trouve des versets sans utiliser explicitement le mot recherché.

> **Prompt :** *"Que dit Jésus sur le fait d'avoir peur du futur ou de s'inquiéter pour le jour d'après ?"*
> *Résultat attendu :* L'IA trouvera des versets parlant "d'anxiété", "le lendemain aura soin de lui-même", "Ne vous inquiétez pas pour votre vie", etc. L'IA expliquera le concept biblique avec douceur.

> **Prompt :** *"Trouve moi l'histoire où un roi d'Égypte pardonne à ses frères."*
> *Résultat attendu :* L'IA trouvera les références (Genèse 50), expliquant comment Joseph a pardonné à ses frères après avoir été vendu.

### Cas d'Usage B : La Logique Calendaire (Rosaire)
L'objectif est de montrer la prise de conscience temporelle.

> **Prompt :** *"Nous sommes Lundi. Si je prie le chapelet aujourd'hui, sur quels mystères dois-je méditer et quel est le premier ?"*
> *Résultat attendu :* L'IA détecte l'intention ROSARY et la date du jour, interroge la logique métier et ressort: "Les Mystères Joyeux. Le premier est l'Annonciation."

### Cas d'Usage C : L'Assistant Paroissial Personnel (Disponibilités)
L'objectif est de prouver une extraction NLU (Natural Language Understanding) complexe transformant du texte libre en requête de filtre.

> **Prompt :** *"J'ai vraiment besoin de me confesser rapidement. Est-ce que le prêtre Jean-Paul est libre un de ces jours ?"*
> *Résultat attendu :* L'IA ne va pas chercher "Jean-Paul" dans la Bible. Elle détecte l'intent AVAILABILITY. Notre backend récupère le planning de Jean-Paul Koffi et ressort la plage horaire du lendemain ou du surlendemain dans la paroisse concernée. L'IA formulera : *"Oui, le Père Jean-Paul Koffi vous accueille pour une confession jeudi prochain entre 14h00 et 17h00 à la paroisse Saint Jean-Baptiste."*

> **Prompt :** *"Est-ce qu'une soeur propose des entretiens pour demain matin ?"*
> *Résultat attendu :* Le routeur extraira le service ("Entretien" -> Accompagnement spirituel), le Rôle ("SISTER"), et la date.

### Cas d'Usage D : Pare-Feu contre les Questions Hors-Sujet
> **Prompt :** *"Peux-tu me donner la recette pour faire un tieboudienne sénégalais ?"*
> *Résultat attendu :* L'extracteur renverra une intention UNKNOWN ou un domaine vide. Le Chatbot refusera gentiment d'entrer dans ce discours et rappellera avec empathie qu'il est un assistant spirituel et paroissial.
