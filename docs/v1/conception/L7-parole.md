# L7 — La Parole

> Conception et livraison du lot L7 (plan §2 L7 ; SRS §3.4 EF-PAR-01 à 05 ; ADR-008, ADR-013). Version du 25/09/2026.

## 1. Contrat

| Route | Accès | Contenu |
|---|---|---|
| `GET /liturgy/today/` · `GET /liturgy/{YYYY-MM-DD}/` | public | `calendar` (calcul local), `source`, `edition`, `notice`, `readings[]`, `audio_url` (AELF seulement), `meditation` |
| `GET /bible/books/…/chapters/{n}/verses/`, `GET /bible/search/` | public | versets de l'édition `BIBLE_EDITION` uniquement |
| `GET /bible/daily-texts/` | public | **seulement si `LITURGY_SOURCE=aelf`** |
| `POST /bible/import/` | `plateforme.admin` | import en tâche de fond (remplace le contrôle `is_superuser`) |
| `GET /rosary/…` | public | inchangé ; `source` (prières) et `meditation_source` (mystères) ajoutés |

Retirées (ADR-013, et ADR-008 : relais du texte AELF sans accord) : `liturgy/v1/informations/`, `liturgy/v1/messes/`, `liturgy/date/<str>/`, `liturgy/readings/<pk>/`. `liturgy/v1/lectures/` (office des lectures) rejoint la Liturgie des Heures gelée. Le module mort `apps/liturgy/views.py` est supprimé.

## 2. Réglages (`config/settings/parole.py`)

| Réglage | Défaut | Rôle |
|---|---|---|
| `LITURGY_SOURCE` | `aelf` | `aelf` : réponse AELF telle quelle (local, recette, production) ; `crampon_refs` : option explicite |
| `LITURGY_ZONE` | `afrique` | zone AELF des références |
| `BIBLE_EDITION` | vide | `Verse.source_file` servi ; **à positionner à `crampon1923` après l'import** |
| `LITURGY_EPIPHANY_ON_SUNDAY` / `LITURGY_ASCENSION_ON_SUNDAY` / `LITURGY_CORPUS_CHRISTI_ON_SUNDAY` | vrai / faux / vrai | usages à confirmer par la Conférence épiscopale |

## 3. Calendrier liturgique local (EF-PAR-02)

`apps/liturgy/calendar.py`, fonctions pures : Pâques (comput grégorien), Avent, Noël, Épiphanie, Baptême, temps ordinaire (numérotation avant et après la Pentecôte, rebours depuis le Christ-Roi), Carême, Triduum, temps pascal ; couleurs (dont rose à Gaudete et Laetare) ; solennités et fêtes du Seigneur avec leurs règles de préséance sur le dimanche et les transferts (saint Joseph, Annonciation, Immaculée Conception) ; cycles dominical (A/B/C) et férial (I/II). Les mémoires et les calendriers propres ne sont pas couverts.

## 4. Lectures du jour (EF-PAR-01)

- `crampon_refs` : les **références** du jour viennent de la synchronisation quotidienne (les citations sont des faits, pas des textes protégés) ; le texte est celui des versets locaux rapprochés par `CitationMatcher`, restreints à `BIBLE_EDITION`. Le texte AELF stocké n'est jamais renvoyé.
- `aelf` (défaut) : réponse de l'API AELF utilisée telle quelle, rien d'inventé ni reconstruit. Chaque lecture : `type` et `citation` (`ref`) AELF, `text` = `contenu` HTML AELF, `verses` = `[]`, `aelf` = l'objet lecture AELF stocké (`Reading.raw_metadata`) sans renommage (titre, intro_lue, refrain_psalmique, verset_evangile…). Toutes les lectures, dans l'ordre AELF. Audio AELF et mention de l'AELF.
- En `crampon_refs`, `aelf` vaut `null`.
- Plus d'appel à l'AELF pendant une requête : si le jour n'est pas synchronisé, l'API renvoie le calendrier et `readings_available=false`.
- **Limite** : les références dépendent encore de l'API AELF. Si son usage même devait cesser, il faudrait un lectionnaire local (tables de références par cycle) : hors V1.

## 5. Bible Crampon 1923 (EF-PAR-03) — étape humaine

Le code sert une seule édition (`BIBLE_EDITION`). Le texte actuellement en base provient du scraper `ETL/aelf/bible` (texte AELF) et ne doit plus être servi. Procédure :

1. Confirmer le statut de domaine public de l'édition Crampon 1923 retenue (plan : « statut à confirmer »).
2. Produire le JSON au format B d'`import_bible` depuis la source retenue (Wikisource), dans l'ETL.
3. `manage.py import_bible <fichier> --source crampon1923`, puis la tâche `populate_tsv`.
4. `BIBLE_EDITION=crampon1923`.
5. Resynchroniser les lectures récentes pour recalculer les rapprochements.

## 6. Chapelet (EF-PAR-04) et méditation (EF-PAR-05)

- Provenance : `Prayer.source`, `Mystery.meditation_source` ; `manage.py rosary_provenance_report` liste les textes sans source (code de sortie 1).
- Méditation du jour : type d'article `meditation`, publié via `/staff/news/` sous `annonces.publier` ; `/liturgy/today/` renvoie la plus locale publiée ce jour pour la paroisse suivie (ou ses ancêtres), sinon une méditation globale.
