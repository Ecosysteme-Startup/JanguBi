# API de la sonothèque paroissiale (`/api/v1/audio/`)

Contrat JSON de la sonothèque (plan suite V2, §5). Lot B3, 27/09/2026. Le schéma OpenAPI
(`schema.yml`, tag `audio`) fait foi pour les types ; ce document donne le sens et des exemples.

## Conventions

- **Authentification** : jeton Keycloak `Authorization: Bearer …`. Les routes marquées
  « compte facultatif » acceptent aussi un appel anonyme (contenus `public` seulement).
- **Erreurs** : format V1 `{"error": {"code", "message", "details"}}`. Une piste, un album ou une
  playlist que vous n'avez pas le droit de voir répond **404** (on ne dit pas qu'elle existe).
- **Visibilité** : `public` (tout le monde), `paroisse` (membres rattachés au nœud de la source :
  paroisse suivie dans le sous-arbre, ou office sur ce nœud, au-dessus ou en dessous), `prive`
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
  "language": "wo",
  "liturgical_season": "ordinaire",
  "tags": ["messe", "chant d'entrée"],
  "description": "Kyrie en wolof, messe du 26e dimanche du temps ordinaire.",
  "duration_seconds": 214.6,
  "source": {"id": "0f6a9c2d-3b1e-4d7a-8c5f-6e2b1a9d4c10", "name": "Chorale Sainte-Cécile", "kind": "chorale"},
  "album": {"id": "a3d9e7f1-2c4b-4e8a-9f1d-6b2c8e4a7d30", "title": "Messe du 27 septembre 2026", "kind": "messe"},
  "position": 1,
  "visibility": "public",
  "published_at": "2026-09-27T13:05:00Z"
}
```

`language` : `fr`, `wo`, `la`, `srr`, `dyo`, `en`, `autre`. `liturgical_season` : `avent`, `noel`,
`careme`, `triduum`, `paques`, `ordinaire` ou `""`.

Objet **piste staff** (`StaffTrack`) : `Track` plus `own_visibility`, `status` (`brouillon`,
`en_file`, `encodage`, `pret`, `echec`), `failure_reason`, `version`, `encoded_version`,
`encoded_at`, `hidden_at`, `created_at`.

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

Filtres : `source`, `kind` (`album`, `messe`, `homelies`, `retraite`). Albums publiés et visibles.

### `POST /audio/albums/` — `audio.publier`

```json
{"source_id": "7c1e4b2a-9d3f-4a6e-b8c1-2d5f7a9e3b20", "kind": "homelies",
 "title": "Homélies du Père Emmanuel Tine", "visibility": "paroisse",
 "description": "Homélies des messes dominicales à Saint-Dominique.", "liturgical_season": ""}
```

Un album naît non publié (`published_at: null`).

### `GET /audio/albums/<id>/` — compte facultatif, cache 10 min

```json
{"album": {"id": "a3d9e7f1-…", "title": "Messe du 27 septembre 2026", "kind": "messe", "…": "…"},
 "tracks": [{"id": "c4f1a8e2-…", "title": "Kyrie", "position": 1, "…": "…"},
            {"id": "d2b7e9c4-…", "title": "Gloria", "position": 2, "…": "…"}]}
```

`PATCH /audio/albums/<id>/` : `kind`, `title`, `description`, `visibility`, `recorded_on`,
`liturgical_season`. Changer la visibilité recalcule celle de toutes ses pistes.

### `POST /audio/albums/<id>/publier/` — `audio.publier`

Publie l'album et ses pistes prêtes non encore publiées ; invalide le cache du catalogue.

### `GET /audio/pistes/<id>/` — compte facultatif

`Track`. `404 piste_introuvable` si non visible.

### `PATCH /audio/pistes/<id>/` — `audio.publier`

```json
{"title": "Kyrie", "performers": ["Chorale Sainte-Cécile"], "composer": "Abbé Joseph Faye",
 "language": "wo", "liturgical_season": "ordinaire", "tags": ["messe"], "description": "…",
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
{"id": "f7a2c9e4-…", "status": "echec", "failure_reason": "Aucune piste audio dans ce fichier.",
 "version": 1, "encoded_version": null, "…": "…"}
```

À la fin de l'encodage, l'auteur reçoit une notification (`audio.encodage_termine` ou
`audio.encodage_echec`, payload `{track_id, title, status, failure_reason}`) dans la liste des
notifications et sur son WebSocket `ws/notifications/`.

### `GET /audio/staff/sources/` et `GET /audio/staff/pistes/?source=<id>&status=<etat>`

Sources où l'on peut publier ; toutes les pistes d'une source avec leur état (`StaffTrack[]`).

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
- `404 piste_introuvable` (pas le droit), `409 piste_pas_prete` (encodage en cours).
- Le client peut appeler `lecture/` dès que la piste est à l'écran pour précharger.

### `GET /audio/lecture/etat/` — reprise multi-appareils

`200` :

```json
{"track": {"id": "c4f1a8e2-…", "title": "Kyrie", "…": "…"}, "position_seconds": 73.5,
 "device_id": "android-mt-diouf", "updated_at": "2026-09-27T10:42:10Z"}
```

`204` s'il n'y a aucune écoute (ou plus le droit d'écouter cette piste).

### `PUT /audio/lecture/etat/`

Toutes les 15 s, à la pause et à la fermeture :

```json
{"track_id": "c4f1a8e2-7b3d-4c9a-a1e6-3f8d2b7c5e50", "position_seconds": 88.0,
 "device_id": "web-mt-diouf", "client_updated_at": "2026-09-27T10:43:02Z"}
```

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
{"type": "notification", "event_type": "playback.state",
 "track_id": "c4f1a8e2-…", "position_seconds": 88.0, "device_id": "web-mt-diouf",
 "updated_at": "2026-09-27T10:43:02Z"}
```

  L'appareil qui a écrit reconnaît son `device_id` et ignore le message ; les autres proposent
  « Reprendre sur cet appareil ». Aucun enregistrement dans la liste des notifications.

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
à l'identique. Rejetés : piste inconnue ou non autorisée, horodatage de plus de 7 jours ou de plus
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
- `GET /audio/moderation/signalements/` (`audio.moderer`) : signalements ouverts du sous-arbre.
- `POST /audio/moderation/signalements/<id>/traiter/` : `{"resolution": "retire"}` (la piste
  disparaît du catalogue, `hidden_at`) ou `{"resolution": "rejete"}`. Tous les signalements
  ouverts de la piste sont clos ensemble ; l'action est journalisée (`AuditEvent`).
