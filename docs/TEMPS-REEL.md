# Temps réel : protocole pour les clients web et mobile

Lot B2 du plan V2 (§4). Ce document décrit ce que le serveur attend et ce qu'il envoie.
Il sert aux équipes web (`JanguBiUI`) et mobile (`JanguBIMobileApp`).

| Besoin | Technique | Point d'entrée |
|---|---|---|
| Messages, lu, réactions, « écrit… » | WebSocket | `wss://…/ws/messaging/conversations/<id>/` |
| Notifications dans l'app, présence | WebSocket | `wss://…/ws/notifications/` |
| Tableaux de bord des dons | SSE (`text/event-stream`) | `GET /api/v1/staff/dons/flux/?noeud=<id>` |
| App fermée | Push FCM et APNs | enregistrement : `POST /api/v1/notifications/devices/` |

Le serveur tourne sous **Daphne (ASGI)**. gunicorn (WSGI) ne sert ni les WebSocket ni les flux SSE.

## 1. Authentification

- **API REST et SSE** : `Authorization: Bearer <jeton Keycloak>`, comme le reste de l'API.
- **WebSocket**, et **SSE avec `EventSource` natif** (qui ne sait pas poser d'en-tête) : ticket à
  usage unique, valable 60 s.
  1. `POST /api/v1/me/ws-ticket/` avec le jeton Keycloak renvoie `{"ticket": "…"}`.
  2. Ouvrir `…?ticket=<ticket>`.
  3. **Chaque ouverture ou reconnexion demande un nouveau ticket.** Un ticket déjà utilisé est refusé.
- Le jeton d'accès ne passe jamais dans une URL.

Codes de fermeture des WebSocket :
- `4401` : ticket invalide ou expiré. Le client rafraîchit son jeton, demande un ticket et rouvre.
- `4001` : socket anonyme.
- `4003` : pas participant de la conversation.

## 2. Présence : « en ligne » et « vu à »

### 2.1 Règles de vie privée

- La présence n'est visible que par les **interlocuteurs** : les personnes avec qui l'on a une
  conversation. Un blocage, dans un sens ou dans l'autre, coupe la présence.
- Réglage « **montrer ma présence** ». Par défaut, il est activé pour le clergé (diacres, prêtres,
  évêques) et le staff (toute personne nommée à un office). Il est désactivé pour les fidèles.
- Une présence masquée ne montre ni « en ligne » ni « vu à ». Les connexions et déconnexions de
  cette personne ne produisent **aucun** événement : leur heure ne peut pas se deviner.
- On ne peut pas interroger la présence d'une personne hors de ses conversations. Les identifiants
  inconnus ou étrangers sont ignorés sans le dire.

### 2.2 Connexion et battement

- Toute WebSocket authentifiée compte une connexion : `ws/notifications/` et
  `ws/messaging/conversations/<id>/`. La personne est « en ligne » dès sa première connexion. Elle
  passe « hors ligne » à la fermeture de la dernière. C'est à ce moment que le « vu à » est écrit.
- Le client envoie un **battement toutes les 25 s** sur la socket de notifications. S'il n'a que la
  socket d'une conversation ouverte, il l'envoie sur celle-ci.

  ```json
  {"type": "presence.ping"}
  ```

  Le serveur répond `{"type": "presence.pong"}`.
- Sans battement pendant **60 s**, la personne est considérée hors ligne pour les lectures. C'est le
  cas d'un réseau coupé ou d'une app tuée. Le battement suivant la remet en ligne.
- Mobile : envoyer le battement seulement au premier plan. Au passage en arrière-plan
  (`AppState`), fermer la socket de notifications proprement : le « vu à » devient exact.
- Web : un seul minuteur par onglet. Si l'onglet est masqué (`visibilitychange`), le battement peut
  continuer : l'onglet reste « en ligne ».

### 2.3 Événement reçu : `presence.changed`

Il arrive sur `ws/notifications/`, envoyé aux interlocuteurs seulement.

```json
{"type": "presence.changed", "user_id": "…", "visible": true, "online": true, "last_seen_at": null}
{"type": "presence.changed", "user_id": "…", "visible": true, "online": false, "last_seen_at": "2026-09-27T10:42:13+00:00"}
{"type": "presence.changed", "user_id": "…", "visible": false, "online": null, "last_seen_at": null}
```

Le dernier cas arrive quand la personne masque sa présence : le client efface l'indicateur.

### 2.4 API REST

- `GET /api/v1/messaging/presence/?users=<uuid>,<uuid>` renvoie l'état de ces personnes, 50 au plus,
  à l'ouverture d'une liste ou d'une conversation. Réponse :

  ```json
  [{"user_id": "…", "visible": true, "online": false, "last_seen_at": "2026-09-27T10:42:13+00:00"}]
  ```

  Seuls les interlocuteurs figurent dans la réponse. Une liste vide ou invalide renvoie une erreur 400.
- `GET /api/v1/me/presence/` renvoie mon réglage :
  `{"montrer_presence": null, "effective": false, "default": false}`.
- `PUT /api/v1/me/presence/` avec `{"montrer_presence": true | false | null}` change mon réglage.
  `null` revient au défaut. Les interlocuteurs sont prévenus si la visibilité change.

### 2.5 Affichage conseillé (maquettes C3)

- « En ligne » : un point discret.
- Hors ligne : « Vu à 10 h 42 » le jour même, puis « Vu hier », puis « Vu le 25 septembre ».
- Présence masquée : rien, pas même une mention « masqué ».

## 3. SSE : tableaux de bord des dons

### 3.1 Ouverture

```
GET /api/v1/staff/dons/flux/?noeud=<uuid paroisse ou diocèse>
Accept: text/event-stream
Authorization: Bearer <jeton>          (ou ?ticket=<ticket> pour EventSource natif)
Last-Event-ID: <dernier id reçu>       (à la reconnexion ; ou ?lastEventId=)
```

Droits :
- **paroisse** : `dons.voir_fonds` par une nomination **sur la paroisse même**, comme la synthèse ;
- **diocèse** : `dons.voir_agregats` quand le catalogue la contient (lot A2), sinon
  `dons.definir_quete_imperee` ;
- MFA exigée dans les deux cas.

Réponses d'erreur, en JSON, avant tout flux :
- `401` : non authentifié, ou ticket déjà utilisé ;
- `403` : sans le droit requis ;
- `404` : nœud inconnu ;
- `400` : le nœud n'est ni une paroisse ni un diocèse.

### 3.2 Format

```
retry: 5000
: flux dons.<uuid>

id: 41
event: dons.operation
data: {"kind":"don","id":"…","fund_id":"…","channel":"en_ligne","status":"confirme","at":"2026-09-27T09:12:00+00:00"}

id: 42
event: dons.synthese_invalidee
data: {"node_id":"…","fund_id":"…","month":"2026-09"}

: ping
```

- `retry:` : délai de reconnexion conseillé (5 s).
- `: ping` : commentaire de battement **toutes les 15 s**. Il empêche les proxys de couper la
  connexion. Les clients l'ignorent.
- `id:` : numéro croissant par flux. Le navigateur le renvoie seul dans `Last-Event-ID`.
- Le serveur ferme le flux au bout de **30 min**. Le client se reconnecte, ce qui revérifie les droits.

### 3.3 Événements

| Événement | Flux | Quand | Données |
|---|---|---|---|
| `dons.operation` | paroisse | Don confirmé ou remboursé ; quête saisie ou rejetée ; quête validée, qui arrive comme un don confirmé en espèces. | `kind` (`don` ou `quete`), `id`, `fund_id`, `channel`, `status`, `at` |
| `dons.synthese_invalidee` | paroisse | Après chaque opération ci-dessus. | `node_id`, `fund_id`, `month` (AAAA-MM) |
| `dons.synthese_invalidee` | diocèse | Une opération dans une paroisse du diocèse. | `node_id` (le diocèse), `month`. Aucune paroisse n'est nommée. |
| `dons.synthese_invalidee` avec `"resync": true` | tous | Reprise impossible : trou trop grand, ou événements expirés après 10 min. | `node_id`, `month`, `resync` |

Les événements ne portent **ni montant ni nom**. À chaque événement, le client recharge ce qu'il
affiche : la synthèse, la liste des opérations, « À traiter ». Ces appels appliquent leurs propres
règles, par exemple les noms masqués sans `dons.voir_donateurs`. Regrouper les rechargements : un
seul appel par seconde au plus (anti-rebond).

### 3.4 Reprise

- À la reconnexion, le client envoie `Last-Event-ID` : le serveur rejoue les événements manqués,
  jusqu'à 50 en 10 min.
- Au-delà, le serveur envoie un seul `dons.synthese_invalidee` avec `resync: true`, et le client
  recharge tout.

### 3.5 Clients

**Web** : on utilise `@microsoft/fetch-event-source`. Il pose l'en-tête `Authorization`, gère
`Last-Event-ID` et se reconnecte.

```ts
await fetchEventSource(`${API}/staff/dons/flux/?noeud=${nodeId}`, {
  headers: { Authorization: `Bearer ${token}` },
  onmessage(ev) {
    if (ev.event === "dons.operation" || ev.event === "dons.synthese_invalidee") scheduleRefetch();
  },
  onerror(err) { if (isAuthError(err)) throw err; /* sinon : reconnexion automatique */ },
  openWhenHidden: false,
});
```

Avec un `EventSource` natif :
- il faut un ticket par ouverture ;
- à l'`onerror`, fermer la source, demander un nouveau ticket et rouvrir avec `?lastEventId=<dernier id>`.

**Mobile (React Native)** : `react-native-sse`, avec l'en-tête `Authorization`. Suivre le dernier
`id` et le repasser à la reconnexion. Fermer le flux en arrière-plan : on recharge au retour au
premier plan.

### 3.6 Infrastructure

- Daphne sert le flux au fil de l'eau.
- Traefik ne met pas les réponses en tampon.
- En-têtes posés par le serveur : `Cache-Control: no-cache, no-transform` et `X-Accel-Buffering: no`
  (pour un éventuel nginx). Pas de compression sur ce chemin.
- Transport interne : la couche Channels (Redis), groupe `sse.dons.<uuid>`. Pour publier depuis
  n'importe quel code serveur, appeler `apps.realtime.sse.sse_publish(stream=…, event=…, data=…)`
  dans un `transaction.on_commit`.
- Un flux ne garde **ni transaction ni connexion Postgres** pendant qu'il est ouvert.

## 4. Notifications push

### 4.1 Enregistrer l'appareil

```
POST /api/v1/notifications/devices/   {"platform": "android" | "ios" | "web", "token": "…"}
DELETE /api/v1/notifications/devices/ {"token": "…"}            (à la déconnexion)
```

- Android et web : jeton **FCM**.
- iOS : jeton **FCM**, donné par `@react-native-firebase/messaging`, ou jeton **APNs natif**
  (64 caractères hexadécimaux). Le serveur choisit le fournisseur d'après la forme du jeton.
- Réenregistrer le jeton à chaque démarrage et à chaque rafraîchissement (`onTokenRefresh`). Cela
  réactive un jeton que le fournisseur avait refusé.

### 4.2 Contenu reçu

- Titre : « Jàngu Bi ». Texte **sans contenu sensible** :
  - message : « Nouveau message du Père Emmanuel Tine », ou « de Marie-Thérèse Diouf », jamais
    d'extrait ;
  - rendez-vous : « Rappel : vous avez un rendez-vous prochainement. » (jamais « confession ») ;
  - demande : « Votre demande a avancé. » ;
  - annonce : « Nouvelle annonce de votre paroisse. » ;
  - sinon : « Vous avez une nouvelle notification. »
- Données, toutes en chaînes : `event_type`, `notification_id` et les identifiants de la
  notification, par exemple `conversation_id`. L'app ouvre l'écran à partir de ces données, puis
  charge le détail par l'API.
- Clé de regroupement : `notification_id` (`collapse_key` sur Android, `apns-collapse-id` sur iOS).
  Un double envoi ne produit qu'une seule notification affichée.
- Canal Android : `jangubi-default`, à créer dans l'app (`FCM_ANDROID_CHANNEL_ID`).

### 4.3 Préférences

- `PUT /api/v1/me/notification-preferences/` accepte le champ `"push": true | false`.
- Dans la plage de silence (22 h à 6 h par défaut), le push est **différé** à la fin du silence.
- Les thèmes coupés (annonces, événements) ne produisent pas de push.

### 4.4 Côté serveur

- Service : `apps.messaging.services_push.push_send(user=…, title=…, body=…, data=…)`. L'envoi part
  dans la tâche Celery `push_deliver` (file `default`) après la transaction.
- Chaque création de `Notification` déclenche le push, par `notification_send` et `people_notify`.
- Un jeton refusé est désactivé (`disabled_at`), pas supprimé :
  - FCM : `UNREGISTERED`, `SENDER_ID_MISMATCH` ou 404 ;
  - APNs : 410, `BadDeviceToken` ou `DeviceTokenNotForTopic`.
- Les erreurs passagères sont relancées pour les seuls appareils concernés : 429, 5xx, réseau,
  jeton d'accès expiré. Le délai double à chaque fois (60 s, 120 s…), 4 fois au plus.

Configuration (variables d'environnement, aucun secret dans le dépôt) :

| Variable | Rôle |
|---|---|
| `PUSH_ENABLED` | `true` pour envoyer. Vaut `false` par défaut. |
| `FCM_PROJECT_ID` | Projet Firebase. Par défaut, celui du compte de service. |
| `FCM_SERVICE_ACCOUNT_JSON` ou `FCM_SERVICE_ACCOUNT_FILE` | Compte de service, rôle « Firebase Cloud Messaging API Admin ». |
| `APNS_TEAM_ID`, `APNS_KEY_ID` | Équipe Apple et identifiant de la clé `.p8`. |
| `APNS_PRIVATE_KEY` ou `APNS_PRIVATE_KEY_FILE` | Clé `.p8`, au format PEM. |
| `APNS_TOPIC` | Bundle id de l'app, `sn.numerisen.jangubi` par défaut. |
| `APNS_USE_SANDBOX` | `true` pour les builds de développement. |

## 5. Réglages du temps réel

| Variable | Défaut | Rôle |
|---|---|---|
| `PRESENCE_TTL_SECONDS` | 60 | Durée de vie de la clé de présence sans battement. |
| `PRESENCE_PING_SECONDS` | 25 | Intervalle attendu du battement (information pour les clients). |
| `SSE_HEARTBEAT_SECONDS` | 15 | Intervalle des commentaires `: ping`. |
| `SSE_RETRY_MILLISECONDS` | 5000 | Valeur du champ `retry:`. |
| `SSE_REPLAY_SIZE`, `SSE_REPLAY_TTL_SECONDS` | 50, 600 | Tampon de reprise par flux. |
| `SSE_MAX_CONNECTION_SECONDS` | 1800 | Durée maximale d'un flux. |
