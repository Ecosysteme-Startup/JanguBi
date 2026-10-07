> **Obsolète — archivé.** L'app `rag` a été supprimée (ADR-016) et la plateforme n'embarque aucune IA (ADR-018,
> `docs/v1/03-DECISIONS-ADR.md`). Ce document décrit un état abandonné ; il est gardé pour l'historique.

# Module RAG (JanguBi)

## Présentation
Le module **RAG** (Retrieval-Augmented Generation) transforme JanguBi d'un simple site web d'informations en un véritable Assistant IA interactif, proactif et hyper-personnalisé, le tout propulsé par le modèle Gemini de Google.

## L'Architecture du "Smart Router"
Le défi majeur de l'IA sur JanguBi est qu'elle doit répondre à 3 domaines fonctionnels très distincts : la Bible, le Rosaire, et les Agendas. L'architecture a donc été pensée en **Pipeline de RAG Structuré** (Multi-Agentique) plûtot qu'en appel direct (Chat simple).

### Le Workflow Étape par Étape :
1. **L'Extractor (Le Routeur Intelligent)** :
   Une requête arrive (`"Quels prêtres confessent demain à Dakar ?"`). Un petit modèle ultra-rapide (`gemini-2.5-flash`) lit la requête et a pour unique but d'en **extraire une structure JSON** stricte (Intention, Date relative traduite en ISO, Topic, Service, Ville).
2. **Les Moteurs (Engines)** :
   Selon l'Intention (BIBLE, ROSARY, AVAILABILITY, ou MIXTE), le système réveille en parallèle 1 à 3 moteurs. 
   - *BibleEngine* : Lance une recherche Full-Text/Vectorielle.
   - *RosaryEngine* : Traduit le sens en jour de la semaine et trouve les mystères en SQL.
   - *AvailabilityEngine* : Fait un lookup sur le planning des ministres pour la date demandée.
3. **Le Context Builder** :
   Les moteurs renvoient du texte brut (ex: les heures des prêtres, les passages de la bible). Ce module assemble tout cela dans un gros bloc de références structurées.
4. **Le Générateur (LLM Final)** :
   Le gros modèle IA reçoit la question originale + le gros bloc de contexte généré de manière sécurisée par notre base Django. L'IA rédige une réponse bien formatée, empathique et polie.

## Sécurité & Confidentialité
Contrairement aux Chatbots "libres", le système JanguBi pratique le **"Grounded RAG"** :
L'IA ne lit *pas* le web et ne puise *pas* dans ses souvenirs internes (qui hallucinent ou peuvent être hérétiques). L'IA est obligée de baser sa réponse à 100% sur les `contextes` exacts que les Moteurs Django valident au préalable. Si nous n'assurons pas le service, l'IA dira qu'elle ne sait pas, empêchant de fausses informations ecclésiales ou temporelles.

## Endpoints API Clés
- `POST /api/v1/rag/query/` : Accepte du simple `{"query": "Priez pour moi..."}`. Est asynchrone (via asgiref `sync_to_async`) pour gérer les appels Google API sans bloquer les travailleurs Django classiques.
