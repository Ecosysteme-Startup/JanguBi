# API de la sonothèque paroissiale (`/api/v1/audio/`)

Contrat JSON de la sonothèque (plan suite V2, §5). Lot B3, 27/09/2026 ; compléments B3b
(espace staff, progression de l'encodage, pochettes, accueil, signalement d'album, limite de débit
des événements), 29/09/2026 ; décisions validées du 29/09/2026 (album réservé visible verrouillé,
téléchargement hors ligne, paroisses multiples, une lecture à la fois). Le schéma OpenAPI
(`schema.yml`, tag `audio`) fait foi pour les types ; ce document donne le sens et des exemples.

## Conventions

- **Authentification** : jeton Keycloak `Authorization: Bearer …`. Les routes marquées
  « compte facultatif » acceptent aussi un appel anonyme (contenus `public` seulement).
- **Erreurs** : format V1 `{"error": {"code", "message", "details"}}`. Une piste, un album ou une
  playlist que vous n'avez pas le droit de voir répond **404** (on ne dit pas qu'elle existe).
  Exception (décision 4) : un contenu `paroisse` **publié** est visible des non-membres, verrouillé ;
  l'écouter ou le télécharger répond **403 `reserve_paroissiens`** (voir §3).
- **Visibilité** : `public` (tout le monde), `paroisse` (membres rattachés au nœud de la source :
  membre — paroisse principale **ou secondaire** — de ce nœud ou d'une paroisse de son sous-arbre,
  ou office sur ce nœud, au-dessus ou en dessous ; voir `GET /me/paroisses/`), `prive`
  (brouillon, visible de ceux qui ont `audio.publier` sur le nœud). La visibilité d'une piste est la
  plus fermée de la sienne et de celle de son album.
- **Droits staff** : `audio.publier` (sources, albums, envois, publication, playlists éditoriales) et
  `audio.moderer` (signalements), lus sur le nœud de la source avec `peut()`. MFA exigée.
- **Aucun classement entre sources** : les listes de sources sont alphabétiques ; « les plus
  écoutés » n'existe qu'à l'intérieur d'une source ; aucun compteur d'écoute n'est exposé.
- Dates en ISO 8601 (UTC). Durées et positions en secondes (décimales).

Identifiants utilisés dans les exemples :

| Objet | Identifiant |
|---|---|
| Paroisse Saint-Dominique (nœud) | `5b7d2c1e-8a41-4f0b-9d7e-2c3f1a6b9e01` |
| Source « Chorale Sainte-Cécile » | `0f6a9c2d-3b1e-4d7a-8c5f-6e2b1a9d4c10` |
| Source « Paroisse Saint-Dominique » | `7c1e4b2a-9d3f-4a6e-b8c1-2d5f7a9e3b20` |
| Album « Messe du 27 septembre 2026 » | `a3d9e7f1-2c4b-4e8a-9f1d-6b2c8e4a7d30` |
| Album « Homélies du Père Emmanuel Tine » | `b8e2f4a6-1d3c-4b9e-8a7f-5c2d9e1b6a40` |
| Piste « Kyrie » | `c4f1a8e2-7b3d-4c9a-a1e6-3f8d2b7c5e50` |
| Piste « Gloria » | `d2b7e9c4-6a1f-4d8b-b3e5-9c1a4f7d2e60` |

Objet **piste** (auditeur), repris partout sous le nom `Track` :

```json
{
  "id": "c4f1a8e2-7b3d-4c9a-a1e6-3f8d2b7c5e50",
  "title": "Kyrie",
  "performers": ["Chorale Sainte-Cécile"],
  "composer": "Abbé Joseph Faye",
  "language": "fr",
  "liturgical_season": "ordinaire",
  "tags": ["messe", "chant d'entrée"],
  "description": "Kyrie de la messe du 26e dimanche du temps ordinaire.",
  "duration_seconds": 214.6,
  "source": {"id": "0f6a9c2d-3b1e-4d7a-8c5f-6e2b1a9d4c10", "name": "Chorale Sainte-Cécile", "kind": "chorale"},
  "album": {"id": "a3d9e7f1-2c4b-4e8a-9f1d-6b2c8e4a7d30", "title": "Messe du 27 septembre 2026", "kind": "messe"},
  "position": 1,
  "visibility": "public",
  "published_at": "2026-09-27T13:05:00Z"
}
```

`language` : `fr`, `wo`, `la`, `srr`, `dyo`, `en`, `autre` (les données de démonstration sont en
`fr`, décision 16). `liturgical_season` : `avent`, `noel`,
`careme`, `triduum`, `paques`, `ordinaire` ou `""`.

Objet **piste staff** (`StaffTrack`) : `Track` plus `own_visibility`, `status` (`brouillon`,
`en_file`, `encodage`, `pret`, `echec`), `failure_reason`, `encoding_step`, `encoding_percent`,
`version`, `encoded_version`, `encoded_at`, `hidden_at`, `created_at`, `plays_30d`.

- `encoding_step` : `""` (pas encore commencé), `analyse`, `normalisation`, `qualites`,
  `forme_onde`, `termine`. `encoding_percent` : 0 à 100. Voir §2.
- `plays_30d` : débuts d'écoute (`start`) des 30 derniers jours, lus dans `PlayEvent`. Renseigné
  seulement dans les listes staff d'**une** source (`GET /audio/staff/pistes/?source=…`,
  `GET /audio/staff/albums/<id>/`) ; `null` ailleurs (suivi d'envoi, publication…). Jamais exposé
  aux auditeurs, jamais comparé entre sources.

Objet **album staff** (`StaffAlbum`) : l'album plus `track_count` (toutes ses pistes, brouillons
compris), `hidden_at` (retiré par la modération), `created_at`, `updated_at`.

---

## 1. Catalogue

### `GET /audio/sources/` — compte facultatif

Filtres : `node` (uuid), `kind` (`paroisse`, `chorale`, `mouvement`). Ordre alphabétique.

```json
[
  {"id": "0f6a9c2d-3b1e-4d7a-8c5f-6e2b1a9d4c10", "name": "Chorale Sainte-Cécile", "kind": "chorale",
   "description": "Chorale de la paroisse Saint-Dominique (Point E).",
   "node": {"id": "5b7d2c1e-8a41-4f0b-9d7e-2c3f1a6b9e01", "name": "Saint-Dominique"},
   "cover_url": null, "is_active": true},
  {"id": "7c1e4b2a-9d3f-4a6e-b8c1-2d5f7a9e3b20", "name": "Paroisse Saint-Dominique", "kind": "paroisse",
   "description": "", "node": {"id": "5b7d2c1e-8a41-4f0b-9d7e-2c3f1a6b9e01", "name": "Saint-Dominique"},
   "cover_url": null, "is_active": true}
]
```

### `POST /audio/sources/` — `audio.publier` sur le nœud

```json
{"node_id": "5b7d2c1e-8a41-4f0b-9d7e-2c3f1a6b9e01", "kind": "chorale", "name": "Chorale Sainte-Cécile",
 "description": "Chorale de la paroisse Saint-Dominique (Point E)."}
```

`201` : l'objet source. `409 source_existe` si le nom est déjà pris sur ce nœud.

### `GET /audio/sources/<id>/` — compte facultatif, cache 10 min

Page d'une source. `most_played` : les plus écoutés **de cette source seulement**.

```json
{
  "source": {"id": "0f6a9c2d-…", "name": "Chorale Sainte-Cécile", "kind": "chorale", "…": "…"},
  "albums": [
    {"id": "a3d9e7f1-2c4b-4e8a-9f1d-6b2c8e4a7d30", "source": {"id": "0f6a9c2d-…", "name": "Chorale Sainte-Cécile", "kind": "chorale"},
     "kind": "messe", "title": "Messe du 27 septembre 2026", "description": "Messe de 10 h 30, 26e dimanche du temps ordinaire.",
     "visibility": "public", "cover_url": null, "recorded_on": "2026-09-27", "liturgical_season": "ordinaire",
     "published_at": "2026-09-27T13:05:00Z"}
  ],
  "playlists": [
    {"id": "e1c7…", "title": "Chants de la Toussaint", "description": "", "visibility": "public",
     "is_editorial": true, "source": {"id": "0f6a9c2d-…", "name": "Chorale Sainte-Cécile", "kind": "chorale"},
     "track_count": 8, "updated_at": "2026-09-20T18:00:00Z"}
  ],
  "recent": ["Track", "…"],
  "most_played": ["Track", "…"]
}
```

`PATCH /audio/sources/<id>/` (`audio.publier`) : `kind`, `name`, `description`, `is_active`.

### `GET /audio/albums/` — compte facultatif

Filtres : `source`, `kind` (`album`, `messe`, `homelies`, `retraite`). Albums publiés et visibles,
**y compris** les albums `paroisse` des paroisses dont on n'est pas membre, avec `"verrouille": true`
(100 au plus). Tout objet album des listes d'auditeur porte `verrouille` (booléen) ; il vaut `false`
dans l'espace staff.

### `POST /audio/albums/` — `audio.publier`

```json
{"source_id": "7c1e4b2a-9d3f-4a6e-b8c1-2d5f7a9e3b20", "kind": "homelies",
 "title": "Homélies du Père Emmanuel Tine", "visibility": "paroisse",
 "description": "Homélies des messes dominicales à Saint-Dominique.", "liturgical_season": ""}
```

Un album naît non publié (`published_at: null`).

### `GET /audio/albums/<id>/` — compte facultatif, cache 10 min

```json
{"album": {"id": "a3d9e7f1-…", "title": "Messe du 27 septembre 2026", "kind": "messe", "verrouille": false, "…": "…"},
 "tracks": [{"id": "c4f1a8e2-…", "title": "Kyrie", "position": 1, "verrouille": false, "…": "…"},
            {"id": "d2b7e9c4-…", "title": "Gloria", "position": 2, "verrouille": false, "…": "…"}],
 "paroisse_requise": null}
```

**Album réservé, vu par un non-membre** (décision 4 ; anonyme compris) : pochette, titre, source
**et** liste des pistes (`Track` complet : titre, durée, position…) avec `verrouille: true`. Cette
réponse ne contient **jamais d'URL** de lecture ; `paroisse_requise` donne la paroisse à ajouter
(« Ajouter cette paroisse » → `POST /me/paroisses/`). Les pistes `prive` n'y figurent pas ; un album
`prive`, brouillon ou retiré répond `404`.

```json
{"album": {"id": "b8e2f4a6-1d3c-4b9e-8a7f-5c2d9e1b6a40", "title": "Homélies du Père Emmanuel Tine",
           "kind": "homelies", "visibility": "paroisse", "cover_url": null,
           "source": {"id": "7c1e4b2a-…", "name": "Paroisse Saint-Dominique", "kind": "paroisse"},
           "verrouille": true, "…": "…"},
 "tracks": [{"id": "9a1e…", "title": "Homélie du 26e dimanche du temps ordinaire", "duration_seconds": 812.0,
             "position": 1, "visibility": "paroisse", "verrouille": true, "…": "…"}],
 "paroisse_requise": {"id": "5b7d2c1e-8a41-4f0b-9d7e-2c3f1a6b9e01", "name": "Saint-Dominique"}}
```

`paroisse_requise` : la paroisse du nœud de la source (ou sa plus proche paroisse ancêtre pour un
mouvement, une CEB) dès que l'album ou l'une de ses pistes est `paroisse` ; `null` sinon, ou si la
source est au-dessus de la paroisse (diocèse, doyenné). Dans un album `public`, une piste `paroisse`
est de même montrée verrouillée aux non-membres.

`PATCH /audio/albums/<id>/` : `kind`, `title`, `description`, `visibility`, `recorded_on`,
`liturgical_season`. Changer la visibilité recalcule celle de toutes ses pistes.

### `POST /audio/albums/<id>/publier/` — `audio.publier`

Publie l'album et ses pistes prêtes non encore publiées ; invalide le cache du catalogue.

### `GET /audio/pistes/<id>/` — compte facultatif

`Track`. `404 piste_introuvable` si non visible.

### `PATCH /audio/pistes/<id>/` — `audio.publier`

```json
{"title": "Kyrie", "performers": ["Chorale Sainte-Cécile"], "composer": "Abbé Joseph Faye",
 "language": "fr", "liturgical_season": "ordinaire", "tags": ["messe"], "description": "…",
 "visibility": "public", "position": 1, "album_id": "a3d9e7f1-2c4b-4e8a-9f1d-6b2c8e4a7d30"}
```

Réponse : `StaffTrack`. L'index de recherche est recalculé.

`POST /audio/pistes/<id>/publier/` (`409 piste_pas_prete` tant que l'encodage n'est pas fini),
`POST /audio/pistes/<id>/depublier/`, `POST /audio/pistes/<id>/reencoder/` (`202`, nouvelle version
depuis le fichier source gardé dans `audio-raw/`).

---

## 2. Envoi et encodage (staff)

### `POST /audio/uploads/` — `audio.publier`

```json
{
  "source_id": "7c1e4b2a-9d3f-4a6e-b8c1-2d5f7a9e3b20",
  "album_id": "b8e2f4a6-1d3c-4b9e-8a7f-5c2d9e1b6a40",
  "title": "Homélie du 26e dimanche du temps ordinaire",
  "visibility": "public",
  "file_name": "homelie-27-09-2026.m4a",
  "file_type": "audio/mp4",
  "file_size": 18874368,
  "rights_confirmed": true
}
```

`201` (stockage S3/R2/MinIO) :

```json
{
  "upload_id": "f7a2c9e4-5b1d-4e3a-9c8f-1d6e2b7a4c70",
  "track": {"id": "f7a2c9e4-…", "title": "Homélie du 26e dimanche du temps ordinaire", "status": "brouillon", "version": 0, "…": "…"},
  "method": "POST",
  "url": "https://stockage.jangubi.sn/jangubi-media",
  "fields": {"acl": "private", "Content-Type": "audio/mp4", "key": "audio-raw/3e9b1c….m4a",
             "policy": "eyJ…", "x-amz-algorithm": "AWS4-HMAC-SHA256", "x-amz-credential": "…",
             "x-amz-date": "20260927T111500Z", "x-amz-signature": "…"},
  "max_size": 524288000,
  "expires_in": 3600
}
```

Le client poste un formulaire `multipart/form-data` vers `url` avec tous les `fields` puis le
champ `file` en dernier. En stockage local (développement), `url` vaut
`…/api/v1/audio/uploads/<id>/local/` et `fields` est vide (champ `file` seul, jeton requis).

Erreurs `400` : `droits_non_confirmes` (case « J'ai les droits sur cet enregistrement » non
cochée), `format_audio` (mp3, m4a, aac, wav, flac, ogg, opus seulement ; extension et type
cohérents), `fichier_trop_gros` (500 Mo), `album_autre_source`. `403 audio_forbidden`.

### `POST /audio/uploads/<id>/terminer/` — l'auteur de l'envoi ou `audio.publier`

Vérifie la présence de l'objet, passe la piste à `en_file` et lance `audio_transcode_task` (file
Celery `media`). Idempotent : un second appel renvoie l'état courant sans relancer.

`202` : `StaffTrack` avec `"status": "en_file", "version": 1`. `400 upload_absent` si le fichier
n'est pas encore arrivé.

### `GET /audio/uploads/<id>/` — suivi de l'encodage

```json
{"id": "f7a2c9e4-…", "status": "encodage", "encoding_step": "qualites", "encoding_percent": 45,
 "failure_reason": "", "version": 1, "encoded_version": null, "plays_30d": null, "…": "…"}
```

`transcode_track` écrit l'étape et l'avancement au début de chaque étape, hors transaction (visible
tout de suite) :

| `encoding_step` | `encoding_percent` | Étape |
|---|---|---|
| `""` | 0 | en file (`en_file`), ou relancé après une erreur technique |
| `analyse` | 0 puis 5 | ffprobe (durée, tags) |
| `normalisation` | 15 | loudnorm EBU R128 |
| `qualites` | 30, 41, 52, 63 | les trois débits HLS puis le MP3 |
| `forme_onde` | 80 puis 90 | forme d'onde, puis dépôt des fichiers dans le stockage |
| `termine` | 100 | `status: "pret"` |

En cas d'échec, `status: "echec"` et l'étape atteinte restent affichées (`failure_reason` dit
pourquoi). Interroger toutes les 2 à 3 s pendant l'encodage suffit ; la notification
`audio.encodage_termine` arrive de toute façon à la fin.

Exemple d'échec :

```json
{"id": "f7a2c9e4-…", "status": "echec", "encoding_step": "analyse", "encoding_percent": 5,
 "failure_reason": "Aucune piste audio dans ce fichier.", "version": 1, "encoded_version": null, "…": "…"}
```

À la fin de l'encodage, l'auteur reçoit une notification (`audio.encodage_termine` ou
`audio.encodage_echec`, payload `{track_id, title, status, failure_reason}`) dans la liste des
notifications et sur son WebSocket `ws/notifications/`.

### `GET /audio/staff/sources/` et `GET /audio/staff/pistes/?source=<id>&status=<etat>`

Sources où l'on peut publier ; toutes les pistes d'une source avec leur état, leur progression
d'encodage et `plays_30d` (`StaffTrack[]`, 200 au plus, les plus récentes d'abord — jamais triées
par écoutes). `source` est obligatoire (`400` sinon) : pas de liste d'écoutes à cheval sur
plusieurs sources. `403 audio_forbidden` sans `audio.publier` sur le nœud de la source.

```json
[{"id": "c4f1a8e2-…", "title": "Kyrie", "status": "pret", "encoding_step": "termine",
  "encoding_percent": 100, "published_at": "2026-09-27T13:05:00Z", "plays_30d": 42, "…": "…"}]
```

---

## 2 bis. Espace staff : albums et pochettes (`audio.publier`)

### `GET /audio/staff/albums/?source=<id>&kind=<type>`

Tous les albums des sources où l'on peut publier (ou d'une seule avec `source`), **brouillons
compris** (`published_at: null`) et albums retirés (`hidden_at`), les plus récents d'abord (500 au
plus). Sans aucune source gérée : `[]`. Avec une `source` non gérée : `403`.

```json
[{"id": "b8e2f4a6-1d3c-4b9e-8a7f-5c2d9e1b6a40",
  "source": {"id": "7c1e4b2a-…", "name": "Paroisse Saint-Dominique", "kind": "paroisse"},
  "kind": "homelies", "title": "Homélies du Père Emmanuel Tine",
  "description": "Homélies des messes dominicales à Saint-Dominique.", "visibility": "paroisse",
  "cover_url": null, "recorded_on": null, "liturgical_season": "", "published_at": null,
  "track_count": 4, "hidden_at": null, "created_at": "2026-09-20T09:00:00Z",
  "updated_at": "2026-09-27T11:20:00Z"}]
```

### `POST /audio/staff/albums/`

Même corps que `POST /audio/albums/` (`source_id`, `kind`, `title`, `visibility`, `description`,
et facultativement `recorded_on`, `liturgical_season`). `201` : `StaffAlbum`, non publié.

### `GET /audio/staff/albums/<id>/`

`{"album": StaffAlbum, "tracks": StaffTrack[]}` : toutes les pistes de l'album (brouillons, en
encodage, en échec) par position, avec `plays_30d`.

### `PATCH /audio/staff/albums/<id>/`

`kind`, `title`, `description`, `visibility`, `recorded_on`, `liturgical_season`. Changer la
visibilité recalcule celle des pistes. `200` : `StaffAlbum`. La publication reste
`POST /audio/albums/<id>/publier/`.

### `POST /audio/staff/albums/<id>/pochette/` — envoi de la pochette

```json
{"file_name": "homelies-saint-dominique.jpg", "file_type": "image/jpeg", "file_size": 812345}
```

`201` : POST présigné vers `audio-covers/<album_id>/…` (bucket privé), comme l'audio :

```json
{"file_id": 1289, "method": "POST", "url": "https://stockage.jangubi.sn/jangubi-media",
 "fields": {"acl": "private", "Content-Type": "image/jpeg", "key": "audio-covers/b8e2f4a6-…/9d1c….jpg", "…": "…"},
 "max_size": 5242880, "expires_in": 3600}
```

En stockage local (développement), `url` vaut `…/api/v1/audio/staff/albums/<id>/pochette/<file_id>/local/`
et `fields` est vide (champ `file` seul, jeton requis, réponse `204`).

Erreurs `400` : `format_image` (jpg, png, webp seulement ; extension et type cohérents),
`image_trop_grosse` (5 Mo), `fichier_vide`. `403 audio_forbidden`.

### `POST /audio/staff/albums/<id>/pochette/terminer/`

```json
{"file_id": 1289}
```

Vérifie la présence de l'objet, sa taille et sa signature (JPEG, PNG ou WebP), le marque valide
(`apps.files`, `upload_finished_at`) et en fait la pochette ; invalide le cache du catalogue.
Idempotent. `200` : `StaffAlbum` avec `cover_url`. `400 upload_absent` (pas encore arrivé),
`400 format_image` (contenu qui n'est pas une image), `404 pochette_introuvable` (fichier d'un
autre album).

---

## 3. Lecture

### `POST /audio/pistes/<id>/lecture/` — compte facultatif

Un seul aller-retour : droit d'écoute (cache 5 min), URL signée, reprise, forme d'onde.

```json
{
  "track": {"id": "c4f1a8e2-…", "title": "Kyrie", "duration_seconds": 214.6, "…": "…"},
  "stream": {
    "format": "hls",
    "master_url": "https://audio.jangubi.sn/audio-hls/c4f1a8e2-7b3d-4c9a-a1e6-3f8d2b7c5e50/1/master.m3u8?verify=1790532000-3q2Nf0x8m1YxJ4b2kQ0hZ6s9tR5vW7yA1cE3gI5kM7o",
    "mp3_url": "https://audio.jangubi.sn/audio-hls/c4f1a8e2-7b3d-4c9a-a1e6-3f8d2b7c5e50/1/audio.mp3?verify=1790532000-3q2Nf0x8m1YxJ4b2kQ0hZ6s9tR5vW7yA1cE3gI5kM7o",
    "expires_at": "2026-09-27T17:20:00Z"
  },
  "resume": {"position_seconds": 73.5, "device_id": "android-mt-diouf", "updated_at": "2026-09-27T10:42:10Z"},
  "waveform": [0.12, 0.34, 0.81, 1.0, 0.77, "… 200 valeurs entre 0 et 1"]
}
```

- `resume` vaut `null` sans compte, sans écoute antérieure, ou si la piste était finie (on repart
  du début).
- Signature valable 6 h sur le **préfixe versionné** : le même `verify` ouvre les manifestes de
  débit et les segments (voir `AUDIO-ARCHITECTURE.md`). Sans CDN : URL MinIO présignée, ou URL
  du média local en développement.
- `404 piste_introuvable` (piste privée, brouillon, retirée, inconnue), `409 piste_pas_prete`
  (encodage en cours).
- `403 reserve_paroissiens` (décision 4) : piste publiée réservée aux paroissiens, et vous n'êtes
  membre ni en principale ni en secondaire. `details.paroisse` sert au bouton « Ajouter cette
  paroisse » (`null` si le contenu relève d'un nœud au-dessus de la paroisse) :

```json
{"error": {"code": "reserve_paroissiens", "message": "Réservé aux paroissiens de Saint-Dominique.",
           "details": {"paroisse": {"id": "5b7d2c1e-8a41-4f0b-9d7e-2c3f1a6b9e01", "name": "Saint-Dominique"}}}}
```
- Le client peut appeler `lecture/` dès que la piste est à l'écran pour précharger.

### `GET /audio/lecture/etat/` — reprise multi-appareils

`200` :

```json
{"track": {"id": "c4f1a8e2-…", "title": "Kyrie", "…": "…"}, "position_seconds": 73.5,
 "device_id": "android-mt-diouf", "updated_at": "2026-09-27T10:42:10Z"}
```

`204` s'il n'y a aucune écoute (ou plus le droit d'écouter cette piste).

### `PUT /audio/lecture/etat/`

Toutes les 15 s, à la pause et à la fermeture, **et au lancement de la lecture** :

```json
{"track_id": "c4f1a8e2-7b3d-4c9a-a1e6-3f8d2b7c5e50", "position_seconds": 88.0,
 "device_id": "web-mt-diouf", "client_updated_at": "2026-09-27T10:43:02Z", "playing": true}
```

`playing` (facultatif, `false` par défaut) : `true` quand cet appareil lit (lecture lancée,
« Reprendre sur cet appareil ») ; `false` à la pause et pour les sauvegardes périodiques d'un
lecteur à l'arrêt.

```json
{"applied": true, "state": {"track": {"…": "…"}, "position_seconds": 88.0, "device_id": "web-mt-diouf",
 "updated_at": "2026-09-27T10:43:02Z"}}
```

- Dernière écriture gagnante sur `client_updated_at`, **borné** par le serveur : jamais dans le
  futur (ramené à l'heure serveur), au plus 24 h en arrière. Position bornée à la durée.
- `applied: false` : un autre appareil a écrit plus récemment ; `state` est l'état qui gagne. La
  position de cette piste est quand même gardée pour sa propre reprise.
- Si l'écriture gagne, le serveur pousse sur le WebSocket `ws/notifications/` de la personne
  (groupe `user_<id>`) :

```json
{"type": "notification", "event_type": "playback.state", "action": "etat", "playing": true,
 "track_id": "c4f1a8e2-…", "position_seconds": 88.0, "device_id": "web-mt-diouf",
 "updated_at": "2026-09-27T10:43:02Z"}
```

  L'appareil qui a écrit reconnaît son `device_id` et ignore le message ; les autres proposent
  « Reprendre sur cet appareil ». Aucun enregistrement dans la liste des notifications.
- **Une lecture à la fois par compte** (décision 10) : quand `playing` vaut `true`, le serveur
  envoie aussi, **même si l'écriture n'a pas gagné** (c'est l'appareil qu'on vient de toucher) :

```json
{"type": "notification", "event_type": "playback.state", "action": "pause",
 "sauf_device_id": "web-mt-diouf", "track_id": "c4f1a8e2-…", "device_id": "web-mt-diouf"}
```

  Tout appareil dont le `device_id` diffère de `sauf_device_id` met sa lecture en pause
  (sans afficher d'erreur) ; celui qui a écrit l'ignore. « Reprendre sur cet appareil » = lancer la
  lecture localement puis `PUT` avec `playing: true`.

### `POST /audio/pistes/<id>/telechargement/` — compte requis (décision 5)

Écoute hors ligne, y compris d'un album réservé si l'on est membre de la paroisse. Mêmes droits que
`lecture/` (`403 reserve_paroissiens`, `404`, `409 piste_pas_prete`). Le fichier reste **dans
l'app** (stockage privé, non exportable).

```json
{"track": {"id": "9a1e…", "title": "Homélie du 26e dimanche du temps ordinaire", "…": "…"},
 "mp3_url": "https://audio.jangubi.sn/audio-hls/9a1e…/1/audio.mp3?verify=1790497800-…",
 "url_expire_le": "2026-09-29T10:30:00Z",
 "version": 1,
 "licence": {"delivree_le": "2026-09-29T10:15:00Z", "expire_le": "2026-10-29T10:15:00Z",
             "paroisse_requise": {"id": "5b7d2c1e-8a41-4f0b-9d7e-2c3f1a6b9e01", "name": "Saint-Dominique"}}}
```

- `mp3_url` : MP3 128 kb/s, URL signée **courte** (15 min, `AUDIO_DOWNLOAD_URL_TTL_SECONDS`) :
  télécharger tout de suite.
- `licence.expire_le` : 30 jours (`AUDIO_OFFLINE_LICENSE_DAYS`), renouvelée par la vérification
  ci-dessous. Au-delà sans renouvellement, l'app supprime le fichier. `paroisse_requise` : `null`
  pour un contenu public.
- `version` : version d'encodage ; si la vérification renvoie une autre version, re-télécharger.
- Limite de débit : 60 par heure et par compte (`AUDIO_DOWNLOAD_THROTTLE_RATE`) → `429`.

### `POST /audio/telechargements/verifier/` — compte requis (décision 5)

À chaque connexion (et au moins une fois par jour en ligne), avec **toutes** les pistes gardées :

```json
{"track_ids": ["9a1e…", "c4f1a8e2-7b3d-4c9a-a1e6-3f8d2b7c5e50", "d2b7e9c4-6a1f-4d8b-b3e5-9c1a4f7d2e60"]}
```

```json
{"verifie_le": "2026-09-29T10:15:00Z",
 "results": [
   {"track_id": "9a1e…", "statut": "a_supprimer", "motif": "plus_membre", "expire_le": null,
    "version": null, "paroisse_requise": null},
   {"track_id": "c4f1a8e2-…", "statut": "valide", "motif": "", "expire_le": "2026-10-29T10:15:00Z",
    "version": 1, "paroisse_requise": null},
   {"track_id": "d2b7e9c4-…", "statut": "a_supprimer", "motif": "retiree", "expire_le": null,
    "version": null, "paroisse_requise": null}
 ]}
```

- `statut` : `valide` (nouvelle `expire_le`, 30 jours) ou `a_supprimer` : l'app efface le fichier.
- `motif` : `plus_membre` (retiré de la paroisse par lui-même ou par la paroisse), `retiree`
  (dépubliée, retirée par la modération, source désactivée), `privee` (devenue privée),
  `introuvable`.
- 500 identifiants au plus (`400` au-delà ou liste vide). Aucune écriture côté serveur : la licence
  vit dans l'app. Limite : 30 par heure et par compte (`AUDIO_DOWNLOAD_VERIFY_THROTTLE_RATE`).

---

## 3 bis. Accueil

### `GET /audio/accueil/` — compte facultatif

Toutes les sections de l'écran d'accueil en un seul appel (10 éléments au plus par section) :

```json
{
  "paroisse": {"id": "5b7d2c1e-8a41-4f0b-9d7e-2c3f1a6b9e01", "name": "Saint-Dominique"},
  "reprendre": [
    {"track": {"id": "…", "title": "Homélie du 26e dimanche du temps ordinaire", "…": "…"},
     "position_seconds": 73.5, "updated_at": "2026-09-27T10:42:10Z"}
  ],
  "nouveautes_ma_paroisse": [{"id": "c4f1a8e2-…", "title": "Kyrie", "…": "…"}],
  "pour_vous": [{"track": {"id": "d2b7e9c4-…", "title": "Gloria", "…": "…"}, "reason": "Parce que vous avez écouté « Kyrie »"}],
  "playlists_paroisse": [{"id": "e1c7…", "title": "Chants de la Toussaint", "is_editorial": true, "track_count": 8, "…": "…"}],
  "temps_liturgique": {"code": "ordinaire", "label": "Temps ordinaire",
                       "tracks": [{"id": "c4f1a8e2-…", "title": "Kyrie", "…": "…"}]}
}
```

- `reprendre` : pistes commencées et pas finies (reprise par piste), les plus récentes d'abord.
  Toujours calculé à l'appel (jamais en cache). `[]` sans compte.
- `nouveautes_ma_paroisse` : dernières publications des sources de la paroisse principale (et de son
  sous-arbre). `[]` sans compte ou sans paroisse (`paroisse: null`).
- `pour_vous` : les 10 premières recommandations de `GET /audio/pour-vous/` (cache par
  utilisateur) ; sans compte, la liste de démarrage à froid publique.
- `playlists_paroisse` : playlists éditoriales publiées des sources de la paroisse principale.
- `temps_liturgique` : pistes dont le temps liturgique (ou celui de l'album) est le temps du jour
  (`apps.liturgy`).
- `nouveautes_ma_paroisse`, `playlists_paroisse` et `temps_liturgique` sont **mis en cache 10 min
  par paroisse** (et par temps liturgique), invalidés à chaque publication. Ils sont calculés avec
  les droits d'un simple fidèle de la paroisse : un membre du staff n'y voit pas ses brouillons ni
  les contenus d'autres nœuds où il a un office (ils restent dans la page de la source).

---

## 4. Recherche

### `GET /audio/recherche/?q=<texte>&limit=20&cursor=<curseur>` — compte facultatif

Plein texte français sans accents (poids : titre > source, album, interprètes, compositeur >
mots-clés, temps liturgique, description) plus trigramme sur le titre (fautes de frappe).
Filtre de visibilité d'abord, puis pertinence, puis popularité à l'intérieur des résultats.

```json
{"results": [{"id": "9a1e…", "title": "Homélie du premier dimanche de Carême", "…": "…"}],
 "next_cursor": "eyJyIjogMC40NjQsICJwIjogMTIsICJpIjogIjlhMWUuLi4ifQ"}
```

`next_cursor: null` en fin de liste. `400 recherche_trop_courte` (moins de 2 caractères),
`400 curseur_invalide`. Exemple : `q=careme` trouve « Carême » ; `q=Sanctsu` trouve « Sanctus ».

---

## 5. Bibliothèque, likes, playlists

### `PUT /audio/pistes/<id>/like/` et `DELETE /audio/pistes/<id>/like/`

`{"liked": true}` / `{"liked": false}`. Idempotents.

### `GET /audio/bibliotheque/`

```json
{"likes": ["Track", "…"],
 "playlists": [{"id": "1d4e…", "title": "Pour le dimanche", "visibility": "prive", "is_editorial": false,
                "source": null, "track_count": 3, "updated_at": "2026-09-27T11:00:00Z", "description": ""}],
 "recent": [{"track": {"…": "…"}, "position_seconds": 30.0, "updated_at": "2026-09-27T10:43:02Z"}]}
```

### Playlists

| Méthode et route | Corps | Réponse |
|---|---|---|
| `GET /audio/playlists/` | | mes playlists |
| `POST /audio/playlists/` | `{"title": "Pour le dimanche", "visibility": "prive"}` ; éditoriale : `+ "source_id"` (`audio.publier`) | `201` playlist |
| `GET /audio/playlists/<id>/` (compte facultatif) | | `{"playlist": …, "tracks": [Track…]}` (pistes filtrées par droits) |
| `PATCH /audio/playlists/<id>/` | `title`, `description`, `visibility`, `published` (éditoriale) | playlist |
| `DELETE /audio/playlists/<id>/` | | `204` |
| `POST /audio/playlists/<id>/pistes/` | `{"track_id": "…"}` (ajout en fin, idempotent) | `201` playlist |
| `DELETE /audio/playlists/<id>/pistes/<track_id>/` | | `204` |
| `PUT /audio/playlists/<id>/ordre/` | `{"track_ids": ["…", "…"]}` (liste complète) | `{"playlist", "tracks"}` |

Une playlist personnelle est `prive` (propriétaire seul) ou `public` (partageable) ; jamais
`paroisse` (`400 visibilite_invalide`). La playlist d'un autre répond `404`. Une playlist
éditoriale n'est visible qu'une fois publiée (`"published": true`).

---

## 6. Événements d'écoute

### `POST /audio/evenements/` — compte facultatif

Lot de 100 événements au plus, envoyé périodiquement (et à la reconnexion pour les écoutes hors
ligne, jusqu'à 7 jours).

```json
{"events": [
  {"client_event_id": "6f0c1b2e-7a3d-4e5f-9b1c-2d3e4f5a6b7c", "track_id": "c4f1a8e2-…", "kind": "start",
   "occurred_at": "2026-09-27T10:40:00Z", "position_seconds": 0, "device_id": "android-mt-diouf"},
  {"client_event_id": "7a1d2c3e-8b4f-4a6e-8c2d-3e4f5a6b7c8d", "track_id": "c4f1a8e2-…", "kind": "complete",
   "occurred_at": "2026-09-27T10:43:35Z", "position_seconds": 214.6, "device_id": "android-mt-diouf"}
]}
```

`kind` : `start`, `progress`, `complete`, `skip`, `like`. `202` :

```json
{"recus": 2, "enregistres": 2, "doublons": 0, "rejetes": 0}
```

Idempotent par `client_event_id` **et** `occurred_at` : en cas de reprise réseau, renvoyer le lot
à l'identique.

**Limite de débit** (throttling DRF) : 30 lots par minute par adresse IP sans compte
(`AUDIO_EVENTS_THROTTLE_RATE_ANON`), 60 lots par minute par compte connecté
(`AUDIO_EVENTS_THROTTLE_RATE_USER`). Au-delà : `429` `{"error": {"code": "throttled", …}}` avec
l'en-tête `Retry-After` (secondes). Le client garde le lot et le renvoie après ce délai (mêmes
`client_event_id`, sans double comptage). Rejetés : piste inconnue ou non autorisée, horodatage de plus de 7 jours ou de plus
de 5 minutes dans le futur. Signaux utilisés par les recommandations : écoute complète (`complete`,
ou `progress` au-delà de 70 %), passe (`skip`, moins de 30 s), likes, ajouts en playlist.

---

## 7. Recommandations

### `GET /audio/pour-vous/`

```json
{"personnalise": true, "demarrage_a_froid": false,
 "results": [
   {"track": {"id": "d2b7e9c4-…", "title": "Gloria", "…": "…"}, "reason": "Parce que vous avez écouté « Kyrie »"},
   {"track": {"id": "…", "title": "Homélie du 26e dimanche du temps ordinaire", "…": "…"}, "reason": "Nouveauté de Paroisse Saint-Dominique"},
   {"track": {"id": "…", "title": "Venez, divin Messie", "…": "…"}, "reason": "Pour le temps de l'Avent"}
 ]}
```

Précalculées chaque nuit (100 au plus), refiltrées par droits à la lecture. Sans historique
(`demarrage_a_froid: true`) : nouveautés de sa paroisse, puis playlists éditoriales, puis temps
liturgique. Réglage désactivé (`personnalise: false`) : même liste non personnalisée.

### `GET /audio/pistes/<id>/ensuite/` — compte facultatif

`Track[]` (10) : voisins précalculés (co-écoute, puis contenu), filtrés par droits ; à défaut la
suite de l'album, puis les plus écoutés de la même source.

### `GET /audio/reglages/` et `PUT /audio/reglages/`

```json
{"recommendations_enabled": false}
```

Désactiver efface tout de suite les recommandations calculées de la personne.

---

## 8. Signalement et modération

- `POST /audio/pistes/<id>/signaler/` : `{"motif": "droits", "comment": "Enregistrement d'un disque du commerce"}`
  (`motif` : `droits`, `inapproprie`, `qualite`, `autre`) → `201`.
- `POST /audio/albums/<id>/signaler/` : même corps, pour un album entier (pochette, présentation,
  ensemble des pistes) → `201`. `404 album_introuvable` si l'album n'est pas visible.
- Objet signalement :

```json
{"id": 12, "cible": "album", "track": null,
 "album": {"id": "a3d9e7f1-…", "title": "Messe du 27 septembre 2026", "…": "…"},
 "motif": "droits", "comment": "Disque du commerce", "status": "ouvert",
 "created_at": "2026-09-28T08:00:00Z", "handled_at": null}
```

  `cible` : `piste` (alors `track` rempli, `album: null`) ou `album` (l'inverse).
- `GET /audio/moderation/signalements/` (`audio.moderer`) : signalements ouverts (pistes et albums)
  du sous-arbre.
- `POST /audio/moderation/signalements/<id>/traiter/` : `{"resolution": "retire"}` (la piste
  disparaît du catalogue, `hidden_at` ; pour un album : l'album **et toutes ses pistes**) ou
  `{"resolution": "rejete"}`. Tous les signalements ouverts de la même cible sont clos ensemble ;
  l'action est journalisée (`AuditEvent`).

---

## 9. Paroisses multiples (décisions 6-8) — hors `/audio/`, utile à la sonothèque

Une paroisse **principale** (accueil, annonces, horaires, dons proposés) et des paroisses
**secondaires** ; principale ou secondaire, l'appartenance ouvre les contenus `paroisse`.
Adhésion libre. `paroisse_suivie` (profil, `GET/PUT /me/paroisse-suivie/`) reste la copie de la
principale.

| Méthode et route | Corps | Réponse |
|---|---|---|
| `GET /me/paroisses/` | | `MaParoisse[]`, la principale d'abord |
| `POST /me/paroisses/` | `{"paroisse_id": "…", "principale": false}` (idempotent ; la première est principale) | `201` `MaParoisse[]` ; `400 not_a_parish` ; `403 retire_par_la_paroisse` |
| `DELETE /me/paroisses/<paroisse_id>/` | | `204` ; la plus ancienne secondaire devient principale ; `404 membre_introuvable` |
| `PUT /me/paroisses/<paroisse_id>/principale/` | | `200` `MaParoisse[]` (une seule principale) ; `404 membre_introuvable` |

```json
[{"paroisse": {"id": "5b7d2c1e-…", "name": "Saint-Dominique", "code": "DAK-P-SAINT-DOMINIQUE", "type": "paroisse"},
  "principale": true, "membre_depuis": "2026-09-01T09:00:00Z"},
 {"paroisse": {"id": "…", "name": "Sainte-Thérèse de Grand-Dakar", "code": "…", "type": "paroisse"},
  "principale": false, "membre_depuis": "2026-09-29T10:00:00Z"}]
```

Côté paroisse (capacité `paroissiens.gerer` : curé, curé in solidum, secrétaire paroissial ; pas
l'évêque — donnée nominative ; MFA) :

- `GET /hierarchy/nodes/<paroisse_id>/membres/?q=&retires=false&limit=&offset=` →
  `{"limit", "offset", "count", "next", "previous", "results": [{"user_id", "first_name", "last_name", "principale",
  "membre_depuis", "retire_le"}]}` ;
- `DELETE /hierarchy/nodes/<paroisse_id>/membres/<user_id>/` → `204` : retrait (journalisé) ; le
  fidèle ne peut plus s'y réinscrire seul (`403 retire_par_la_paroisse`) et ses téléchargements de
  cette paroisse passent `a_supprimer` / `plus_membre` à la vérification suivante ;
- `POST /hierarchy/nodes/<paroisse_id>/membres/<user_id>/retablir/` → `200` membre.

Annonces : `GET /me/feed/` reste le fil de la principale (et des contenus globaux, diocésains) ;
`GET /me/feed/secondaires/?paroisse=<id>` est le **fil séparé** des paroisses secondaires (même
format paginé, articles de ces paroisses et de leur sous-arbre seulement).
