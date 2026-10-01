# API Parole — « Pour vous aujourd'hui »

Lot B4 du plan suite V2 (§6). Backend des recommandations de versets et de livres.
Toutes les routes sont sous `/api/v1/bible/`, authentifiées (jeton Keycloak), au format
d'erreur V1 (`{"error": {"code", "message", "details"}}`).

| Méthode | Route | Rôle |
|---|---|---|
| `POST` | `evenements/` | Envoyer des signaux de lecture, par lots, idempotent |
| `DELETE` | `evenements/` | Effacer mon historique de lecture |
| `GET`, `POST` | `signets/` | Lister, poser un signet ou surligner |
| `GET`, `PATCH`, `DELETE` | `signets/{id}/` | Lire, changer la couleur ou la note, retirer |
| `GET`, `PUT` | `reglages/` | Réglage `personnalisation_parole` |
| `GET` | `pour-vous/` | « Pour vous aujourd'hui » |

Principes, repris du plan :
- aucun score n'est exposé, ni stocké dans la réponse ; seulement des raisons courtes ;
- pas de profilage spirituel affiché ;
- la personnalisation se désactive, et l'historique s'efface ;
- aucune mention d'« IA » dans les textes renvoyés.

## 1. Signaux de lecture — `POST bible/evenements/`

L'app met les événements en file (hors ligne compris) et les envoie par lots de 200 au plus.
Chaque événement porte un `client_event_id` choisi par l'app (un UUID) : un lot renvoyé deux
fois n'enregistre rien la seconde fois.

```json
{
  "evenements": [
    {
      "client_event_id": "5b0e8c1e-2f61-4c1b-9d0a-6f1f3f7a9e10",
      "type": "lu",
      "livre_id": 49,
      "chapitre": 9,
      "verset_debut_id": 25871,
      "verset_fin_id": 25897,
      "termine": false,
      "occurred_at": "2026-09-26T21:40:00Z"
    },
    {
      "client_event_id": "a4f2d7c3-1c55-4a8e-b0e3-0d5a3c1e22f4",
      "type": "surligne",
      "verset_debut_id": 25893,
      "occurred_at": "2026-09-26T21:42:10Z"
    }
  ]
}
```

| Champ | Type | Obligatoire | Sens |
|---|---|---|---|
| `client_event_id` | chaîne (64 max) | oui | Clé d'idempotence, unique par fidèle |
| `type` | `lu`, `signet`, `surligne`, `recherche`, `lectio` | oui | `recherche` : verset ouvert depuis les résultats (la requête n'est jamais envoyée) |
| `verset_debut_id`, `verset_fin_id` | entier | l'un des deux, ou le chapitre | Plage dans un même chapitre ; remise dans l'ordre si besoin |
| `livre_id` + `chapitre` | entier + numéro | si pas de verset | Chapitre entier |
| `termine` | booléen | non (`false`) | Chapitre lu jusqu'au bout |
| `occurred_at` | date-heure ISO 8601 | oui | Un horaire dans le futur est ramené à maintenant |

Réponse `200` :

```json
{ "recus": 2, "enregistres": 2, "rejetes": [], "personnalisation_parole": true }
```

- `rejetes` liste les `client_event_id` dont la référence est inconnue (verset supprimé,
  chapitre inexistant, plage sur deux chapitres). Le reste du lot est enregistré : l'app peut
  vider sa file.
- Personnalisation désactivée : rien n'est enregistré, `enregistres` vaut 0 et
  `personnalisation_parole` vaut `false`. L'app peut alors cesser d'envoyer.
- `400 validation_error` si un événement n'a ni verset ni chapitre, ou si le lot dépasse 200.

## 2. Effacer l'historique — `DELETE bible/evenements/`

Réponse `204`. Efface tous les signaux de lecture et les recommandations précalculées qui en
découlent. Les signets restent : ce sont des contenus du fidèle, qu'il retire un par un
(`DELETE bible/signets/{id}/`).

## 3. Signets et surlignages — `bible/signets/`

Un signet par verset et par fidèle. Sans couleur, c'est un signet ; avec une couleur, un
surlignage. Poser un signet sur un verset déjà marqué met à jour la couleur et la note.

`POST bible/signets/`

```json
{ "verset_id": 25893, "couleur": "jaune", "note": "Porter sa croix chaque jour" }
```

`couleur` : `""` (signet), `jaune`, `vert`, `bleu`, `rose`, `violet`. `note` : 2 000 caractères
au plus.

Réponse `201` (même forme pour `GET` et `PATCH` sur `signets/{id}/`) :

```json
{
  "id": 318,
  "verset_id": 25893,
  "reference": "Luc 9, 23",
  "livre_id": 49,
  "chapitre": 9,
  "numero": 23,
  "texte": "Et il disait à tous : « Si quelqu'un veut venir après moi, qu'il se renonce lui-même, qu'il prenne sa croix chaque jour, et qu'il me suive. »",
  "type": "surligne",
  "couleur": "jaune",
  "note": "Porter sa croix chaque jour",
  "created_at": "2026-09-26T21:42:10Z",
  "updated_at": "2026-09-26T21:42:10Z"
}
```

`GET bible/signets/` est paginé (`limit`, `offset` ; enveloppe `{count, next, previous,
results}`), du plus récent au plus ancien. Un signet d'un autre fidèle répond `404`.

Les signets comptent comme signaux pour « Pour vous aujourd'hui » : l'app n'a pas besoin
d'envoyer en plus un événement `signet` ou `surligne` quand elle passe par cette route.

## 4. Réglage — `bible/reglages/`

```json
{ "personnalisation_parole": true }
```

Activé par défaut. `PUT` avec `false` :
- arrête l'enregistrement des signaux ;
- retire les recommandations précalculées ;
- `pour-vous/` sert alors le verset des lectures du jour, sans « lecture à continuer ».

L'historique déjà enregistré n'est pas effacé par ce réglage : on propose à côté le bouton
« Effacer mon historique » (`DELETE bible/evenements/`).

## 5. « Pour vous aujourd'hui » — `GET bible/pour-vous/`

La route lit la ligne précalculée cette nuit (table `DailyRecommendation`). Sans ligne pour
aujourd'hui, elle sert le verset des lectures du jour (voir §5.3). Elle ne calcule jamais à la
demande : la réponse reste rapide le dimanche matin.

### 5.1 Contrat

| Champ | Type | Sens |
|---|---|---|
| `date` | date | Jour de la recommandation (heure de Dakar) |
| `personnalise` | booléen | `true` : calcul de la nuit ; `false` : verset des lectures du jour |
| `personnalisation_parole` | booléen | État du réglage |
| `verset` | Verset ou `null` | Le verset proposé |
| `autres_versets` | Verset[] (0 à 2) | Deux autres propositions, chacune d'un livre différent |
| `lecture_a_continuer` | objet ou `null` | Dernier chapitre ouvert et pas terminé ; s'il a été terminé, le chapitre suivant |
| `livre_suggere` | objet ou `null` | Livre pas encore commencé, le plus proche de ses lectures |
| `plan_suggere` | objet ou `null` | Plan de lecture publié, non suivi, le plus proche. Toujours `null` tant que les plans sont gelés (ADR-006, `bible.avance`) |
| `raisons` | chaîne[] | Raisons du verset principal (2 au plus), à afficher telles quelles |

Verset : `{id, reference, livre {id, nom, slug}, chapitre, numero, texte, raisons[]}`.
Lecture à continuer : `{reference, livre, chapitre, reprendre_au_verset}` (`reprendre_au_verset`
peut être `null`). Livre suggéré : `{id, nom, slug, raison}`. Plan suggéré :
`{id, titre, description, raison}`.

Raisons possibles :
- « En lien avec l'évangile du jour », « En lien avec le psaume du jour », « En lien avec les
  lectures du jour » ;
- « En ce temps de l'Avent », « En ce temps de Noël », « En ce temps du Carême », « En ces
  jours saints », « En ce temps pascal » ;
- « Parce que vous lisez Luc » (le livre qui pèse le plus dans ses lectures récentes) ;
- en repli : « Tiré de l'évangile du jour », « Tiré des lectures du jour ».

### 5.2 Exemple : Marie-Thérèse Diouf, dimanche 27 septembre 2026

Contexte : 26e dimanche du temps ordinaire, année A. Lectures : Ez 18, 25-28 ; Ps 24 ;
Ph 2, 1-11 ; évangile Mt 21, 28-32 (les deux fils envoyés à la vigne). Marie-Thérèse, paroissienne
de Saint-Dominique (Point E), lit l'évangile de Luc depuis deux semaines. Hier soir, elle a lu
Luc 9 jusqu'au verset 27 et a surligné Lc 9, 23. Elle n'a jamais ouvert les Actes des Apôtres.

`GET /api/v1/bible/pour-vous/` — réponse `200` :

```json
{
  "date": "2026-09-27",
  "personnalise": true,
  "personnalisation_parole": true,
  "verset": {
    "id": 23412,
    "reference": "Matthieu 7, 21",
    "livre": { "id": 47, "nom": "Matthieu", "slug": "matthieu" },
    "chapitre": 7,
    "numero": 21,
    "texte": "Ce ne sont pas ceux qui me disent : Seigneur, Seigneur ! qui entreront dans le royaume des cieux ; mais celui qui fait la volonté de mon Père qui est dans les cieux, celui-là entrera dans le royaume des cieux.",
    "raisons": ["En lien avec l'évangile du jour", "Parce que vous lisez Luc"]
  },
  "autres_versets": [
    {
      "id": 30118,
      "reference": "Jacques 1, 22",
      "livre": { "id": 66, "nom": "Jacques", "slug": "jacques" },
      "chapitre": 1,
      "numero": 22,
      "texte": "Mettez la parole en pratique, et ne vous contentez pas de l'écouter, en vous trompant vous-mêmes.",
      "raisons": ["En lien avec l'évangile du jour", "Parce que vous lisez Luc"]
    },
    {
      "id": 29164,
      "reference": "Philippiens 2, 5",
      "livre": { "id": 58, "nom": "Philippiens", "slug": "philippiens" },
      "chapitre": 2,
      "numero": 5,
      "texte": "Ayez en vous les mêmes sentiments dont était animé le Christ Jésus.",
      "raisons": ["En lien avec les lectures du jour", "Parce que vous lisez Luc"]
    }
  ],
  "lecture_a_continuer": {
    "reference": "Luc 9",
    "livre": { "id": 49, "nom": "Luc", "slug": "luc" },
    "chapitre": 9,
    "reprendre_au_verset": 27
  },
  "livre_suggere": {
    "id": 51,
    "nom": "Actes",
    "slug": "actes",
    "raison": "Parce que vous lisez Luc"
  },
  "plan_suggere": null,
  "raisons": ["En lien avec l'évangile du jour", "Parce que vous lisez Luc"]
}
```

Les identifiants sont ceux d'une base d'exemple ; les textes sont ceux de l'édition servie
(`BIBLE_EDITION`, Crampon 1923 en V1). Aucun verset de Luc 9 n'est proposé : elle l'a lu
depuis moins de 60 jours.

### 5.3 Repli : verset des lectures du jour

Servi quand :
- c'est un démarrage à froid (aucun signal) ;
- le fidèle est inactif (aucun signal depuis 30 jours, donc pas de précalcul) ;
- la personnalisation est désactivée ;
- ou le précalcul de la nuit n'a pas tourné.

```json
{
  "date": "2026-09-27",
  "personnalise": false,
  "personnalisation_parole": true,
  "verset": {
    "id": 24110,
    "reference": "Matthieu 21, 28",
    "livre": { "id": 47, "nom": "Matthieu", "slug": "matthieu" },
    "chapitre": 21,
    "numero": 28,
    "texte": "Mais que vous en semble ? Un homme avait deux fils ; s'adressant au premier, il lui dit : Mon fils, va aujourd'hui travailler à ma vigne.",
    "raisons": ["Tiré de l'évangile du jour"]
  },
  "autres_versets": [],
  "lecture_a_continuer": null,
  "livre_suggere": null,
  "plan_suggere": null,
  "raisons": ["Tiré de l'évangile du jour"]
}
```

On prend le premier verset de l'évangile, sinon celui de la première lecture disponible. Sans
lectures du jour en base, `verset` vaut `null`. `lecture_a_continuer` reste servi en repli si la
personnalisation est active et qu'un chapitre est en cours.

## 6. Calcul (précalcul nocturne)

Tâche Celery `apps.bible.tasks.bible_reco_recompute_task`, file `reco`, planifiée à 3 h 30
(Beat, entrée `bible_reco_recompute`). Elle est idempotente : une ligne par fidèle et par jour,
réécrite si la tâche est livrée deux fois. Elle purge les lignes de plus de 7 jours.

1. **Fidèles concernés** : comptes actifs avec un signal ou un signet depuis 30 jours, sauf
   personnalisation désactivée.
Proximité **lexicale**, sans IA ni modèle (ADR-018), calculée dans PostgreSQL à partir de la
colonne `tsv` des versets (plein texte `fr_unaccent`, index GIN).

2. **Profil de mots** : mots des versets lus et marqués sur les 90 derniers jours, chacun pondéré
   par sa **rareté** dans toute la Bible (`log((N + 1) / (df + 1))` : « croix » pèse, « dire »
   presque pas) ; un mot présent dans plus de 2 % des versets (« le », « était », « Seigneur »)
   est ignoré (`PAROLE_RECO_MAX_DF_RATIO`) ; on garde les 12 mots les plus lourds.
   - Poids : lu et recherche 1 ; signet et lectio 2 ; surlignage 2,5.
   - Décroissance : le poids d'un signal diminue de moitié tous les 30 jours.
   - Un chapitre lu compte pour un signal, réparti sur ses versets.
3. **Candidats** : les 200 versets qui partagent le plus ces mots (somme des poids des mots
   communs, rapportée à la longueur du verset), plus les versets des lectures du jour.
4. **Filtre** : pas de verset lu, ni de chapitre lu, depuis 60 jours ; pas de verset déjà marqué.
5. **Bonus** :
   - +0,15 × proximité avec les lectures du jour (mots marquants de l'évangile s'il est là) ;
   - +0,10 si le verset fait partie des lectures du jour ;
   - +0,05 pour un livre de saison (Isaïe en Avent, Actes au temps pascal…).
6. **Diversité** : au plus un verset par livre parmi les trois proposés.
7. **Livre suggéré** : livre jamais ouvert qui rassemble le plus de candidats proches (ses trois
   meilleurs versets).
8. **Plan suggéré** : plan publié non suivi dont les passages couvrent le plus les livres lus.
   Désactivé tant que `bible.avance` est gelé.

Les proximités sont ramenées entre 0 et 1 (1 = le verset le plus proche) avant les bonus.

Réglages (`config/settings/parole.py`, surchargeables par variable d'environnement) :
`PAROLE_RECO_HALF_LIFE_DAYS` (30), `PAROLE_RECO_HISTORY_DAYS` (90),
`PAROLE_RECO_EXCLUDE_READ_DAYS` (60), `PAROLE_RECO_ACTIVE_DAYS` (30), `PAROLE_RECO_CANDIDATES`
(200), `PAROLE_RECO_LITURGY_BONUS` (0,15), `PAROLE_RECO_READING_BONUS` (0,10),
`PAROLE_RECO_SEASON_BONUS` (0,05), `PAROLE_RECO_LITURGY_REASON_MIN` (0,6),
`PAROLE_RECO_RETENTION_DAYS` (7).

Exploitation :
- Un worker doit consommer la file `reco` (`celery -A apps.tasks worker -Q celery,reco`, ou un
  worker dédié).
- Aucun modèle à télécharger ni à charger en mémoire : le calcul est une suite de requêtes SQL
  (quelques secondes pour toute la Bible), identique en test, en CI et en production.
- Un fidèle dont les lectures n'ont aucun mot exploitable n'a pas de recommandation
  personnalisée et reçoit le repli.

## 7. Confidentialité (loi 2008-12)

- L'historique de lecture est une donnée religieuse sensible. Il n'est jamais journalisé, et il
  n'y a pas d'écran d'administration Django pour ces tables.
- Aucun texte de recherche n'est stocké : seulement le verset ouvert depuis les résultats.
- Export des données personnelles (`GET /api/v1/me/export/`) : section `parole` avec les
  réglages, les signets et l'historique de lecture.
- Suppression du compte : signaux, signets, recommandations et réglage sont effacés.
- Aucune donnée d'autres modules (dons, confession, messagerie) n'entre dans le calcul.
