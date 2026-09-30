# Données de test réalistes (`seed_realiste`)

Une seule commande remplit une base **locale** ou de **recette** avec un monde crédible : paroisses,
fidèles, staff, dons et quêtes sur douze mois, vie paroissiale, sonothèque, écoutes et lectures, puis
recalcul des recommandations. Reproductible (graine), réversible (`--reset`), **jamais en production**.

Plan de référence : `JanguBIMobileApp/docs/PLAN-DONNEES-DE-TEST.md` (décisions de l'utilisateur ci-dessous).

## Démarrer

```bash
make seed-realiste                 # local : échelle petite, médias légers, vérification (< 1 min)
make seed-realiste-reset           # retire exactement le lot (graine 2026 par défaut)
make seed-charge                   # échelle grande (COPY en masse), sans fichiers audio
make seed-realiste APP=jangubi ENV=staging          # (serveur, dépôt Infrastructure) médias puis échelle moyenne
make seed-realiste APP=jangubi ENV=staging RESET=1   # (serveur, dépôt Infrastructure) remise à zéro MANUELLE
make seed-realiste APP=jangubi ENV=staging TRAFIC=10min  # (serveur) dons et écoutes simulés en continu
```

Hors Docker :

```bash
SEED_ALLOWED=true python manage.py seed_realiste --profil local --echelle petite --medias legers --verifier
```

Options (`--help`) :

| Option | Rôle |
|---|---|
| `--profil local\|recette` | recette : comptes Keycloak des personas, médias lus dans le bucket MinIO `seed-assets` |
| `--echelle petite\|moyenne\|grande` | volumes ci-dessous |
| `--graine 2026` | même graine, mêmes données (noms, montants, dates relatives au jour du semis) ; le lot s'appelle `realiste-<graine>` |
| `--modules tous\|socle,dons,vie,audio,parole` | sous-ensemble ; les dépendances sont ajoutées d'office |
| `--medias complets\|legers\|aucun` | voir « Médias » |
| `--historique 12` | mois d'historique des dons et des écoutes (13 au plus : rétention des écoutes) |
| `--reset` | supprime exactement le lot de la graine, rien d'autre |
| `--verifier` | contrôle les invariants et affiche le rapport ; code de sortie non nul si un invariant échoue |
| `--simuler-trafic 10min` | après le semis, dons et écoutes en continu par les vrais services |
| `--medias-dossier <chemin>` | album libre fourni (jamais commité) : ses pistes servent de chants et de musique |
| `--bible-json <chemin>` | JSON de la Bible (AELF) importé par `import_bible` si la Bible est absente |
| `--piper-voix <modèle.onnx>` | voix Piper (sinon `PIPER_VOICE`) |
| `--hors-ligne` | aucun appel réseau (AELF, Keycloak) : replis directs |

## Musique de démonstration (pack de samples, local et recette)

La sonothèque de démo peut utiliser une sélection de 10 pistes instrumentales calmes (piano, orgue, cordes,
flûtes) tirées du pack « The Polyphonic Elements Vol. 6 ». **Jamais en production ni dans Git** : sa licence
n'autorise pas la diffusion des boucles telles quelles. La sélection (fichiers retenus, titres français,
crédits) est versionnée dans `seed_assets/musique-demo.yaml` ; le pack reste sur votre machine.

```bash
# 1. Décompresser Polyphonic.Elements6.rar dans seed_assets/ (ignoré par Git) :
#    seed_assets/The Polyphonic Elements Vol.6/...
make musique-demo              # → seed_assets/musique-demo/ : 10 FLAC + credits.yaml
make seed-realiste-musique     # sonothèque de démo avec cette musique (--medias complets)
```

Hors Docker : `python manage.py prepare_musique_demo --pack <dossier du pack> --sortie <dossier>`, puis
`seed_realiste --medias-dossier <dossier>`.

**En recette, une seule fois** : `prepare_musique_demo --publier` copie les 10 FLAC et `credits.yaml` dans le
bucket MinIO `seed-assets/musique-demo/` du serveur (bucket privé, jamais servi au public). Ensuite, même après
une remise à zéro de la base, `seed_realiste --profil recette --medias complets --musique-demo` reprend la
musique dans ce bucket : plus besoin du pack. `--musique-demo` lit d'abord `seed_assets/musique-demo/` s'il
existe, sinon le bucket. Si le bucket `seed-assets` est vidé, repartir du RAR (copie de référence hors Git). En `--medias legers`, seules les 4 premières pistes servent (extraits
de 30 s) ; en `--medias complets`, les 10.

## Échelles

| Échelle | Usage | Paroisses | Fidèles | Dons (12 mois) | Pistes | Écoutes | Durée cible |
|---|---|---|---|---|---|---|---|
| `petite` | local, démo, tests d'écran | 3 | 300 | ~4 000 | 40 | ~20 000 | < 1 min |
| `moyenne` | recette | 12 | 5 000 | ~80 000 | 250 | ~600 000 | < 10 min |
| `grande` | tests de charge | 40 | 50 000 | ~1 M | 1 500 | ~5 M (partitions sur 13 mois) | < 45 min, `COPY` |

Les paroisses peuplées sont la paroisse pilote (Saint-Dominique), la seconde paroisse de `seed_demo`
(Sainte-Thérèse de Grand-Dakar), puis des paroisses `SEED-PAR-nn` créées dans les doyennés de Dakar.

## Garde-fous

- **Refus net** si `ENV`/`DJANGO_ENV` vaut `production`, si `JANGUBI_ENVIRONMENT` vaut `production`, ou si
  `SEED_ALLOWED` n'est pas vrai (les cibles `make` le passent explicitement).
- **Un seul lot à la fois** : un lot d'une autre graine doit d'abord être retiré (`--reset --graine N`).
- Adresses `@demo.jangubi.sn`, téléphones dans la plage fictive `+221 70 000 xx xx`, noms générés depuis des
  listes locales (aucun nom réel de clerc en poste).
- **Aucune tâche Celery n'est envoyée pendant le semis** (pas de push, pas d'e-mail, pas de notification
  envoyée) : seules les écritures en base ont lieu. Exception nommée : l'encodage audio de `--medias complets`.
- Les **personas** de `seed_demo` (comptes de connexion) restent intactes ; elles servent d'auteurs, de
  staff de la paroisse pilote et reçoivent aussi de l'activité (écoutes, lectures) pour voir « Pour vous ».

## Architecture

- Orchestrateur : `apps/core/management/commands/seed_realiste.py`.
- Registre : `apps/core/seeding/registry.py` — un semeur par module dans `apps/<app>/seeders.py`, découvert
  automatiquement, ordonné par phase (hiérarchie → personnes → appartenances → contenus → dons → audio →
  parole → activité → recalculs) et par dépendances.
- **Point d'extension** : une nouvelle application (intentions de messe, validation du clergé, outils du
  staff, recherche…) ajoute son `seeders.py` avec `@register` (exemple dans la docstring du registre et dans
  `apps/core/tests/test_seed_realiste.py::test_registry_extension_point`). Rien à changer ailleurs.
- Traces : table `core.SeedRecord` (lot, semeur, modèle, identifiant) pour les objets racines ; les
  dépendants sont retrouvés par leurs clés (dons d'un fonds, messages d'une conversation). Les événements
  d'écoute et de lecture sont marqués (`device_id = seed-realiste`, `client_event_id = seed-…`).
- Un second lancement **complète sans dupliquer** : un semeur déjà passé pour le lot est sauté ; les
  semeurs « toujours rejoués » (Bible, liturgie, comptes Keycloak, recalculs) sont idempotents.
- Hasard : un `random.Random` par semeur, dérivé de la graine (un module rejoué seul donne les mêmes
  données) ; identifiants des fidèles, dons et pistes tirés de la graine.
- Insertion en masse : `apps/core/seeding/bulk.py` (`COPY … FROM STDIN`) pour les dons, leur journal et
  les événements d'écoute (écrits au fil de l'eau par blocs de 200 000).

| Semeur | Module | Contenu |
|---|---|---|
| `bible` | parole | Bible réelle : rien si présente ; sinon `import_bible --bible-json` puis indexation |
| `liturgie` | parole | synchronisation AELF réelle (`AelfService.sync_daily_data`) de J-1 à J+7 ; sonde rapide, repli sans réseau |
| `hierarchie` | socle | référentiel et personas si absents, paroisses supplémentaires, lieux, horaires (samedi soir, dimanche, semaine) |
| `comptes_keycloak` | socle | recette : comptes Keycloak des personas (`KC_DEMO_PASSWORD`), rôle `platform_admin` |
| `personnes` | socle | fidèles (60 % de moins de 35 ans, ~6 % de mineurs), présence et `last_seen_at` variés |
| `appartenances` | socle | une principale par fidèle, 20 % avec 1 ou 2 secondaires, retraits par la paroisse ; staff (curé, vicaires, secrétaire, économe) |
| `annonces`, `agenda`, `confessions`, `actes`, `messagerie` | vie | annonces du dimanche, articles, lettres diocésaines, réactions et lectures ; événements et inscriptions ; créneaux, réservations et annulations ; demandes d'actes dans tous les statuts avec pièces « SPÉCIMEN » ; conversations chiffrées, un blocage, notifications et préférences |
| `dons` | dons | voir ci-dessous |
| `sonotheque`, `ecoutes`, `audio_reco` | audio | catalogue et médias ; écoutes par profils, likes, playlists, reprises, signalements ; `recompute_all` |
| `parole`, `parole_reco` | parole | lectures sur 90 jours (quotidien, évangile en continu, occasionnel), signets, surlignages ; « Pour vous » |

### Dons et quêtes

- Calendrier réel : messes du samedi soir et du dimanche selon les horaires de chaque lieu, grandes fêtes
  (Cendres, Rameaux, Pâques, Ascension, Assomption, Toussaint, Noël), Pentecôte (une partie des fidèles à
  Popenguine), quêtes impérées diocésaines (Carême de partage, vocations, Popenguine, Denier de
  Saint-Pierre, Journée missionnaire, Grand Séminaire de Brin), fin de mois et hivernage.
- En ligne : montants log-normaux arrondis aux coupures, rares gros dons ; Wave ~55 %, Orange Money ~30 %,
  carte ~10 %, Free Money ~5 % ; canaux app Android, iOS, site, QR ; ~15 % anonymes, ~25 % frais couverts ;
  ~8 % d'échecs et d'expirations ; reçus numérotés sans trou par paroisse et par an.
- Espèces : une quête par messe, deux compteurs, validation par une autre personne, quelques saisies
  rejetées puis ressaisies, dépôts en banque sous 48 h (10 % en retard), remises à la curie des quêtes
  impérées confirmées par l'économe diocésain.
- Reversements hebdomadaires de l'agrégateur rapprochés (un écart), incidents de paiement (tardif, montant
  incohérent, un résolu), un remboursement, une correction d'un mois clos, nouvelles de campagne.
- **Clôtures mensuelles** de tous les mois écoulés par le vrai service (`month_close`).
- Campagnes : toiture de la chapelle (Saint-Dominique, objectif 4 500 000, 60 % atteints) et une campagne
  close par paroisse.
- **Septembre 2026 à Saint-Dominique reproduit exactement le jeu de la spec** (1 214 830 FCFA : 356 330 en
  ligne en 47 dons, 858 500 en espèces en 9 quêtes, une quête de 64 000 à confirmer, 3 paiements en attente),
  à partir des mêmes constantes que les tests (`apps/donations/seed_septembre.py`).

## Médias (décisions de l'utilisateur)

| Mode | Contenu |
|---|---|
| `aucun` | pistes sans fichier, rendus fictifs : tests d'écran et de charge |
| `legers` | extraits de 30 s encodés **une fois par extrait** par la vraie chaîne (`transcode` : normalisation, HLS 3 débits, MP3, forme d'onde), puis déposés pour chaque piste |
| `complets` | fichiers entiers déposés comme source ; l'encodage part sur la file `media` (worker `celery-media`) ; sans courtier joignable, encodage direct par `transcode_track` (noté). `--verifier` attend la fin des encodages (30 min au plus) |

Sources, par ordre de préférence :

1. **Album fourni** : `--medias-dossier <chemin>` (album open source de l'utilisateur, **jamais commité**).
   Ses pistes servent de chants et de musique. Attribution lue dans `credits.yaml` (facultatif) du dossier :

   ```yaml
   album: {titre: "…", artiste: "…", licence: "CC BY 4.0", source: "https://…"}
   pistes:
     "01-kyrie.mp3": {titre: "Kyrie", compositeur: "…", interpretes: ["…"], attribution: "…"}
   ```

2. **Manifeste** `seed_assets/manifest.yaml` (domaine public, CC0, CC BY/BY-SA ; pochettes Unsplash comme
   l'app) : `python manage.py fetch_seed_assets` télécharge une fois, vérifie les sha256 et range dans
   `~/.cache/jangubi-seed/` (local, `JANGUBI_SEED_CACHE` pour changer) ou dans le bucket MinIO
   **`seed-assets`** de la recette (`--profil recette`). `--epingler` écrit les sha256 manquants.
   Aucun binaire dans Git.
3. **Voix** (homélies, lectures, retraites) : synthèse vocale **Piper** si le binaire `piper` et une voix
   (`--piper-voix` ou `PIPER_VOICE`, `PIPER_BIN`) sont disponibles, lisant des textes rédigés pour le projet
   (`apps/core/seeding/data/textes.yaml`). **Repli ffmpeg** sinon : bruit rose filtré dans la bande de la voix
   et modulé au rythme des syllabes (reconnaissable comme un signal de test). Le semis n'échoue jamais faute
   de Piper ; le rapport le signale.
4. **Musique ffmpeg** (accords tenus) quand il n'y a ni album ni fichier du manifeste en cache.

Les crédits de chaque piste sont dans sa description (« Crédits : … »). Pochettes des sources : monogramme
et couleur générés (Pillow). Pièces jointes des demandes d'actes : PDF et JPEG filigranés « SPÉCIMEN —
données fictives ».

## Bible et lectures : vraies données

Rien n'est généré. La Bible vient de `import_bible` (`--bible-json`, ex. `init/bibles/format/json/bible-fr-aelf.json`,
source `AELF` par défaut, `--bible-source` pour changer) ; les lectures viennent de la synchronisation AELF
réelle. Sans réseau (ou `--hors-ligne`), l'étape est sautée et signalée ; la « lecture du jour » des profils
quotidiens se replie sur une rotation des évangiles. « Pour vous » (Parole) compare des embeddings : avec
`EMBEDDING_PROVIDER=stub` (tests, poste local par défaut), il reste vide et le rapport le dit ; en recette,
`EMBEDDING_PROVIDER=local`, `seed_embeddings`, puis `seed_realiste --modules parole`.

## Vérification (`--verifier`)

- somme des opérations (dons comptés + ajustements) = synthèse, pour chaque paroisse et chaque mois, et
  égale aux totaux figés des clôtures ;
- septembre 2026 de Saint-Dominique = jeu de la spec ;
- une paroisse principale par fidèle, `paroisse_suivie` à jour, curé et économe dans chaque paroisse ;
- pistes `pret` avec leurs 3 débits HLS (et fichiers présents dans le stockage hors `aucun`) ;
- événements d'écoute dans les partitions mensuelles (aucun dans la partition par défaut) ;
- recommandations audio calculées ; « Pour vous » (Parole) calculé quand les embeddings le permettent ;
- adresses en `@demo.jangubi.sn`, messagerie sans mineur.

## Local, recette, clients

- **Local** : `make seed-realiste` ; web `NEXT_PUBLIC_API_MOCKING=false` ; mobile `USE_MOCKS=false` avec
  `API_URL=http://10.0.2.2:8000/api` (émulateur Android) ou l'IP du poste.
- **Recette** : `make seed-realiste APP=jangubi ENV=staging` sur le serveur (voir `docs/RECETTE.md`). Remise à zéro **manuelle uniquement**
  (`RESET=1`, puis `SEED_ARGS="--graine 2027"` pour une nouvelle graine) ;
  aucune tâche planifiée.
- Les écoutes semées tombent dans les partitions mensuelles ; celles de plus de 13 mois sont purgées par
  la tâche mensuelle, comme en production.

## Tests

`apps/core/tests/test_seed_realiste.py` (échelle petite, sans réseau, médias `aucun` et `legers`) :
garde-fous, registre et point d'extension, invariants, jeu de septembre, idempotence, remise à zéro,
reproductibilité, encodage réel des extraits.
