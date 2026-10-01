# Module Bible (JanguBi)

## Présentation
Le module **Bible** est au cœur de l'application JanguBi. Il stocke, indexe et permet la consultation de l'intégralité des écritures saintes (Ancien et Nouveau Testament).

## Fonctionnalités Principales
1. **Consultation Hiérarchique** : Naviguer de Testament ➔ Livre ➔ Chapitre ➔ Versets.
2. **Recherche plein texte** : PostgreSQL, configuration `fr_unaccent` (français, sans accents, racinisé) ; syntaxe web (`"expression exacte"`, `-mot`, `or`).
3. **Tolérance aux fautes** : repli trigramme (`pg_trgm`, index GIN) quand le plein texte ne trouve rien.

Aucune IA ni recherche vectorielle (ADR-018) : pas de modèle à charger, pas de pic de mémoire.

## Architecture
- **Modèles** : `Testament`, `Book`, `Chapter`, `Verse`.
- **Champs Spécifiques** :
  - `Verse.tsv` : vecteur plein texte PostgreSQL (index GIN `idx_verse_tsv`), rempli par `populate_tsv_task`.
  - `Verse.text` : index trigramme `idx_verse_trgm` pour le repli.
- **Services** : `SearchService` (`apps/bible/services/search_service.py`) : score = 0,6 × `ts_rank` + 0,4 × similarité trigramme.

## Endpoints API Clés
- `GET /api/v1/bible/testaments/` : Liste exhaustive pour le menu.
- `GET /api/v1/bible/books/` : Liste des livres (filtrable).
- `GET /api/v1/bible/books/<id>/chapters/<num>/verses/` : Lecture classique (paginée).
- `GET /api/v1/bible/search/?q=...` : moteur de recherche (le paramètre `hybrid` des anciens clients est accepté et sans effet).
