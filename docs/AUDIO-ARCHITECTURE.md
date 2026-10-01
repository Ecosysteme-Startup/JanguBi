# Sonothèque : architecture (upload → encodage → CDN → lecture)

Lot B3 (plan suite V2, §2 à §5), 27/09/2026. Contrat des routes : `docs/API-AUDIO.md`. Code :
`apps/audio/`, réglages : `config/settings/audio.py`.

## 1. Vue d'ensemble

```
 Staff (web / mobile)                      API Django (Daphne)                Stockage objet (bucket privé)
 ────────────────────                      ───────────────────                ─────────────────────────────
 1. POST /audio/uploads/  ───────────────▶ piste « brouillon »
    (case « j'ai les droits »)              + POST présigné (500 Mo, types audio)
 2. POST multipart ───────────────────────────────────────────────────────▶ audio-raw/<nom>.m4a
 3. POST /audio/uploads/<id>/terminer/ ──▶ vérifie l'objet (HEAD), version+1,
                                            « en_file », on_commit →  RabbitMQ, file « media »
                                                                          │
                                           Worker Celery ffmpeg ◀─────────┘
                                           (verrou Redis + version)
                                           ffprobe → loudnorm −16 LUFS → FLAC
                                           → HLS AAC 6 s × 3 débits, MP3 128k,
                                             forme d'onde 200 pics, master.m3u8 ──▶ audio-hls/<id>/<v>/…
                                           « pret » + notification (in-app + WS)

 Fidèle                                                                    Cloudflare (CDN + Worker)
 ──────                                                                    ─────────────────────────
 4. POST /audio/pistes/<id>/lecture/ ────▶ droit d'écoute (cache 5 min)
                                           URL signée ?verify=<exp>-<sig>
                                           + reprise + forme d'onde
 5. GET master.m3u8?verify=… ─────────────────────────────────────────────▶ Worker : vérifie la signature du préfixe,
    GET bas/index.m3u8?verify=…                                             recopie verify dans les manifestes,
    GET bas/seg_00000.ts?verify=… ◀────────────────────────────────────────  sert les segments depuis le cache (1 an)
 6. PUT /audio/lecture/etat/ (15 s) ─────▶ dernière écriture gagnante ──▶ WS « playback.state » (groupe user_<id>)
 7. POST /audio/evenements/ (lots) ──────▶ audio_play_event (partitionnée par mois)
                                           │  3 h : audio_reco_recompute_task (file « reco »)
                                           └▶ voisins (co-écoute, contenu) + 100 recos / utilisateur
```

## 2. Upload

- `POST /audio/uploads/` crée la piste (`brouillon`), un `File` (`apps.files`) dont la clé est
  `audio-raw/<uuid>.<ext>`, et renvoie un **POST présigné S3** (`apps.integrations.aws`) limité par
  politique : `Content-Type` imposé, `content-length-range` 1 octet → 500 Mo, ACL `private`,
  validité 1 h (`AUDIO_UPLOAD_PRESIGNED_EXPIRY`).
- Types acceptés (liste blanche, extension **et** type MIME cohérents) : mp3, m4a, aac, wav, flac,
  ogg, opus.
- La case « J'ai les droits sur cet enregistrement » est obligatoire ; l'heure de confirmation est
  gardée (`rights_confirmed_at`) et l'envoi est journalisé (`AuditEvent audio.piste.televerser`).
- En développement sans S3 (`FILE_UPLOAD_STORAGE=local`), le client envoie le fichier à
  `POST /audio/uploads/<id>/local/`.
- Le fichier source reste dans `audio-raw/` : `POST /audio/pistes/<id>/reencoder/` produit une
  nouvelle version sans nouvel envoi.

## 3. Encodage (`audio_transcode_task`, file `media`)

| Étape | Commande (résumé) |
|---|---|
| Lecture | `ffprobe -show_format -show_streams` : durée, tags (titre, artiste…), refus si aucun flux audio ou plus de 4 h |
| Normalisation | `-af loudnorm=I=-16:TP=-1.5:LRA=11` (EBU R128, un passage) → FLAC 44,1 kHz stéréo intermédiaire |
| HLS bas | mono ; **HE-AAC 32 kb/s** si `libfdk_aac` est présent, sinon **AAC-LC 48 kb/s** (voir ci-dessous) |
| HLS moyen | AAC-LC 64 kb/s stéréo |
| HLS haut | AAC-LC 128 kb/s stéréo |
| Segments | `-f hls -hls_time 6 -hls_playlist_type vod -hls_segment_type mpegts -hls_flags independent_segments` |
| Maître | `master.m3u8` écrit par nous : `BANDWIDTH` (crête) et `AVERAGE-BANDWIDTH` mesurés sur les segments, `CODECS` |
| Hors ligne | MP3 128 kb/s (`libmp3lame`), tags ID3 titre et interprètes |
| Forme d'onde | PCM mono 8 kHz → 200 pics (max absolu par tranche), normalisés à 1 → `waveform.json` et base |

**Débit bas** : le HE-AAC de ffmpeg n'existe qu'avec `libfdk_aac`, absent des builds distribués
(licence non libre) et de l'image actuelle. L'AAC-LC natif à 32 kb/s est nettement dégradé ; on
encode donc en AAC-LC 48 kb/s mono (environ 22 Mo par heure, adapté à la 2G/3G). Si l'équipe
construit une image ffmpeg avec `libfdk_aac`, le HE-AAC 32 kb/s est choisi automatiquement
(`transcode.has_encoder`).

Arborescence déposée (dernier fichier écrit : `master.m3u8`, la version n'est lisible qu'une fois
complète) :

```
audio-hls/<track_id>/<version>/
  master.m3u8
  bas/index.m3u8   bas/seg_00000.ts …
  moyen/index.m3u8 moyen/seg_00000.ts …
  haut/index.m3u8  haut/seg_00000.ts …
  audio.mp3
  waveform.json
```

**Idempotence et reprises** (une file peut livrer deux fois) :
- verrou Redis par piste (`cache.add`, 30 min) : un second worker répond `verrouille` ;
- la tâche porte `(track_id, version)` : version dépassée → `perime` ; déjà prête → `deja_fait` ;
- dossier versionné et immuable : un réencodage écrit `<version+1>/`, l'ancien reste servi par le
  cache CDN jusqu'à la bascule ;
- erreur technique : 3 nouvelles tentatives (30 s, 60 s, 120 s), la piste revient `en_file` avec le
  motif ; à la dernière, `echec` + motif ; fichier invalide : `echec` tout de suite, sans retente ;
- fin : notification de l'uploader (`audio.encodage_termine` / `audio.encodage_echec`) par le
  service de notifications existant (liste in-app + WebSocket `ws/notifications/`).

**Worker ffmpeg séparé** : `celery -A apps.tasks worker -Q media -c 2` sur une machine avec
ffmpeg ; `-Q reco -c 1` pour le calcul nocturne ; les autres tâches restent sur `default`.
Le routage est déclaré par les tâches (`queue=`) et dans `CELERY_TASK_ROUTES` (fusionné avec les
routes globales si un autre lot les déclare).

## 4. Lecture signée

`POST /audio/pistes/<id>/lecture/` vérifie l'identité (jeton Keycloak ou anonyme), l'autorisation
(visibilité et appartenance au nœud, décision en cache Redis 5 min dont la clé change à chaque
modification de la piste) et renvoie l'URL du `master.m3u8`.

### Signature (style Cloudflare)

```
prefixe   = "/audio-hls/<track_id>/<version>/"
expiration = maintenant + 6 h            (secondes Unix, AUDIO_SIGNED_URL_TTL_SECONDS)
signature = base64url(HMAC-SHA256(AUDIO_CDN_SIGNING_SECRET, prefixe + expiration)), sans « = »
URL       = AUDIO_CDN_BASE_URL + prefixe + "master.m3u8?verify=" + expiration + "-" + signature
```

- La signature couvre le **préfixe**, pas un fichier : le même jeton ouvre les manifestes de débit
  et tous les segments de cette version, et rien d'autre (autre version, autre piste : refus).
- Les segments ne sont pas signés un par un : ils sont servis sous un chemin non devinable, signé
  au niveau du préfixe, comme le prévoit le plan (§5.3).
- Référence Python de la vérification : `apps/audio/signing.py::verify_path` (testée).
- Sans CDN (`AUDIO_CDN_BASE_URL` vide) : URL MinIO présignée en S3 (en dev, donner à `audio-hls/`
  une politique de lecture anonyme sur MinIO, les segments n'étant pas présignés), ou URL du
  média local (`/media/…`) en stockage local.

### Worker Cloudflare de référence

Les lecteurs HLS (hls.js, AVPlayer, ExoPlayer) demandent les URI **relatives** des manifestes sans
recopier la query string : le Worker ajoute `verify` à chaque URI quand il sert un `.m3u8`.

```js
// Worker lié au bucket R2 « jangubi-media » (binding AUDIO) ; secret SIGNING_SECRET.
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const parts = url.pathname.split("/").filter(Boolean);        // audio-hls / id / version / …
    if (parts[0] !== "audio-hls" || parts.length < 4) return new Response("Introuvable", { status: 404 });
    const verify = url.searchParams.get("verify") || "";
    const [exp, sig] = verify.split(/-(.+)/);
    if (!exp || !sig || Number(exp) < Date.now() / 1000) return new Response("Lien expiré", { status: 403 });
    const prefix = `/${parts.slice(0, 3).join("/")}/`;
    const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(env.SIGNING_SECRET),
      { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(prefix + exp)));
    const expected = btoa(String.fromCharCode(...mac)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    if (expected !== sig) return new Response("Signature invalide", { status: 403 });

    // Cache partagé par tous : clé SANS la query string.
    const cacheKey = new Request(`${url.origin}${url.pathname}`);
    let response = await caches.default.match(cacheKey);
    if (!response) {
      const object = await env.AUDIO.get(url.pathname.slice(1));
      if (!object) return new Response("Introuvable", { status: 404 });
      const headers = new Headers();
      object.writeHttpMetadata(headers);                           // Content-Type et Cache-Control posés à l'écriture
      response = new Response(object.body, { headers });
      ctx.waitUntil(caches.default.put(cacheKey, response.clone()));
    }
    if (!url.pathname.endsWith(".m3u8")) return response;
    const text = await response.text();                             // recopie de verify dans les URI relatives
    const body = text.split("\n").map((l) => (l && !l.startsWith("#") ? `${l}?verify=${verify}` : l)).join("\n");
    return new Response(body, { headers: response.headers });
  },
};
```

## 5. En-têtes de cache (§5.6)

Posés à l'écriture de chaque objet (`apps/audio/storage.py`) :

| Objet | `Content-Type` | `Cache-Control` |
|---|---|---|
| Segments `*.ts` | `video/mp2t` | `public, max-age=31536000, immutable` (chemin versionné) |
| Manifestes `*.m3u8` | `application/vnd.apple.mpegurl` | `public, max-age=60` |
| `audio.mp3` | `audio/mpeg` | `public, max-age=31536000, immutable` |
| `waveform.json` | `application/json` | `public, max-age=31536000, immutable` |
| Pochettes | type de l'image | immuables (nom unique à l'envoi) |

Côté API : catalogue (pages de source et d'album) en cache Redis 10 min par niveau d'accès
(public, membre, gestion) ; toute publication, modification ou retrait incrémente une version
globale du catalogue (`audio:catalog:version`), ce qui invalide toutes les entrées d'un coup.

## 6. Reprise et synchronisation multi-appareils

- `PUT /audio/lecture/etat/` toutes les 15 s, à la pause et à la fermeture ; la base est la
  source de vérité (`PlaybackState` : une ligne par personne ; `PlaybackPosition` : une par piste).
- Dernière écriture gagnante sur l'horodatage client, borné par le serveur (jamais dans le futur,
  au plus 24 h en arrière).
- Si l'écriture gagne : `group_send("user_<id>", {"type": "notification.push", "event_type":
  "playback.state", …})`. L'enveloppe `notification.push` est celle que le `NotificationConsumer`
  existant relaie déjà ; aucune modification du consumer et aucune ligne `Notification` en base.
- Au démarrage, `GET /audio/lecture/etat/` pour proposer « Reprendre sur cet appareil ».

## 7. Événements d'écoute et partitionnement

- Table `audio_play_event` **partitionnée par mois** (`PARTITION BY RANGE (occurred_at)`), créée par
  la migration SQL `apps/audio/migrations/0002_play_event_partitioned.py` ; modèle Django
  `PlayEvent` en `managed = False` (lecture par l'ORM, écriture en SQL).
- Clé primaire `(id, occurred_at)` ; idempotence : index unique `(client_event_id, occurred_at)` et
  `INSERT … ON CONFLICT DO NOTHING`.
- Pas de clé étrangère (un `TRUNCATE` des tables Django échouerait) : les jointures vers
  `audio_track` ignorent les événements orphelins.
- Partition `DEFAULT` en filet de sécurité ; `audio_play_event_partitions_task` (le 1er du mois,
  1 h 10) crée le mois courant et les deux suivants, déplace les lignes tombées dans `DEFAULT`, et
  supprime les partitions de plus de 13 mois.

## 8. Recommandations (`audio_reco_recompute_task`, file `reco`, 3 h 05)

1. Voisins **co-écoute** : cosinus binaire utilisateur × piste sur 90 jours (écoutes complètes,
   likes, ajouts en playlist), en SQL, 50 par piste, au moins 2 auditeurs communs.
2. Voisins **contenu**, en SQL sur les métadonnées, sans IA ni modèle (ADR-018) : même album
   0,30 ; même temps liturgique (le sien, sinon celui de l'album) 0,15 ; mots-clés communs
   0,25 × Jaccard ; même source 0,10 ; même compositeur 0,05 ; interprètes communs 0,05 × Jaccard ;
   titres proches 0,10 × similarité trigramme. Seuil 0,10, 50 par piste (poids 0,6 face à la
   co-écoute). Une piste neuve sans album se rattache au moins aux pistes de sa source.
3. Par utilisateur actif : voisins de ses signaux récents (demi-vie 30 jours), nouveautés de sa
   paroisse, temps liturgique du jour ; on retire ce qu'il a déjà écouté, passé ou aimé ; filtre
   par droits ; 100 au plus, raison lisible (« Parce que vous avez écouté « Kyrie » »).
4. Réglages : `AUDIO_RECO_ENABLED` (global) et « recommandations personnalisées » par personne.
   Aucune donnée de dons, de confession ou de messagerie n'est lue.

## 9. À faire par l'équipe (Cloudflare R2 et CDN)

1. Créer le bucket R2 `jangubi-media` (privé) ; clés d'API S3 R2 dans `AWS_S3_ACCESS_KEY_ID`,
   `AWS_S3_SECRET_ACCESS_KEY`, `AWS_S3_ENDPOINT_URL=https://<compte>.r2.cloudflarestorage.com`,
   `AWS_S3_REGION_NAME=auto`, `AWS_STORAGE_BUCKET_NAME=jangubi-media`, `FILE_UPLOAD_STORAGE=s3`.
2. CORS du bucket : `POST` depuis `https://jangubi.sn` et l'app (POST présigné) ; `GET`/`HEAD` sur
   le domaine CDN.
3. Domaine `audio.jangubi.sn` → Worker ci-dessus lié au bucket (binding `AUDIO`), secret
   `SIGNING_SECRET` = `AUDIO_CDN_SIGNING_SECRET` côté Django (32 octets aléatoires, jamais en dépôt),
   `AUDIO_CDN_BASE_URL=https://audio.jangubi.sn`.
4. Règle de cache : respecter les en-têtes d'origine ; clé de cache sans query string (le Worker
   le fait) ; niveau « Cache Everything » sur `audio-hls/*`.
5. Aucun accès public direct au bucket (tout passe par le Worker) ; `audio-raw/` jamais exposé.
6. Rotation du secret : déployer d'abord le Worker acceptant l'ancien et le nouveau secret, puis
   changer `AUDIO_CDN_SIGNING_SECRET`, puis retirer l'ancien après 6 h.
7. Worker Celery `-Q media` sur une machine avec ffmpeg (≥ 6) et assez de disque temporaire
   (environ 2 fois la taille du plus gros fichier), alerte sur la longueur de la file `media`.
8. Préchauffage CDN à la publication (plan §5.6) : non fait dans ce lot (voir le rapport).
