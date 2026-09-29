# Administration des comptes synchronisée avec Keycloak

Branche `claude/v1-admin-keycloak`. Objectif : **jamais un compte d'un seul côté**. Toute action
d'administration se fait dans l'interface Jàngu Bi et se répercute dans Keycloak ; tout changement
fait dans Keycloak (console, inscription, profil) revient dans l'application.

## 1. Constat (audit de l'existant, avant ce lot)

| Sujet | État trouvé |
|---|---|
| Création des comptes | Uniquement **à la première connexion** : `person_from_identity` (`apps/authentication/keycloak.py`) crée le `BaseUser` à partir du jeton (ou rattache un compte migré dont l'e-mail est vérifié). Aucun parcours d'administration ne créait de compte. |
| Clergé | `apps/invitations` : invitation par e-mail, la personne s'inscrit elle-même dans Keycloak puis accepte ; validation par `comptes.valider`. |
| Liaison | `BaseUser.keycloak_sub` (unique, nul tant que la personne ne s'est pas connectée). Des comptes pouvaient donc exister d'un seul côté : inscrit dans Keycloak jamais connecté, compte migré non lié, compte supprimé dans la console Keycloak. |
| Rôles | Realm : `fidele`, `staff` (synchronisé depuis les nominations, tâche `keycloak_staff_sync_task` + réconciliation nocturne), `platform_admin` (à la main dans Keycloak). Droits métier : offices et capacités (`apps/hierarchy/authz.py`). |
| Administration | `platform/accounts/` (plateforme seulement) : liste, fiche, verrouiller/déverrouiller, fermer les sessions, exiger la MFA. Pas de création, modification, suppression, ni de portée diocèse/paroisse. |
| Suppression | Par la personne (`/me/account/`) : anonymisation puis suppression Keycloak différée (tâche réessayée). Rien dans l'autre sens : un compte supprimé dans la console Keycloak restait actif dans l'application. |
| Profil | Le nom modifié dans l'application (`me_profile_update`) n'était pas poussé dans Keycloak. L'admin Django permettait de créer / supprimer un `BaseUser` sans Keycloak. |

## 2. Conception

```
               Interface admin (web)  ──► /api/v1/admin/…  (services_admin)
                                              │  même transaction : base + Admin REST API
                                              ▼
 Application (BaseUser, Profile) ◄──────────► Keycloak (realm jangubi / jangubi-staging)
        ▲                                         │
        │ account_pull (Keycloak fait foi         │ événements utilisateur + admin
        │ pour l'identité)                        │ conservés 90 jours
        └── keycloak_events_poll (chaque minute, curseur) ◄──┘
        └── keycloak_reconcile (chaque heure, rapport)       (+ webhook SPI : option, désactivée)
```

- **Client** : `apps/integrations/keycloak/` — `KeycloakAdminClient` (HTTP, compte de service
  `jangubi-admin-sync`, délais 3 s connexion / 10 s lecture, erreurs typées :
  `KeycloakUnavailableError` (réseau, délai, 5xx), `KeycloakNotFoundError`, `KeycloakConflictError`,
  `KeycloakForbiddenError`, `KeycloakBadRequestError`) et `FakeKeycloakAdmin` (en mémoire, tests et
  développement hors ligne : `KEYCLOAK_ADMIN_BACKEND=fake`). `get_keycloak_admin()` choisit.
- **Modèle** (`apps/users`) : `BaseUser.admin_node` (nœud gestionnaire), `keycloak_platform_admin`
  (miroir du rôle, pour la portée), `keycloak_synced_at`, `keycloak_sync_error` ; `KeycloakEvent`
  (dédoublonnage, jamais de représentation stockée), `KeycloakSyncCursor`, `KeycloakSyncRun` (rapport).
- **Capacité** `comptes.gerer` (migration `hierarchy/0015`) : évêque diocésain, vicaire général,
  chancelier, curé, curé in solidum, plateforme.

## 3. Portée (`apps/users/scope_admin.py`)

Plateforme > chancellerie / diocèse > paroisse. Un titulaire de `comptes.gerer` gère un compte si :

1. ce n'est ni le sien, ni celui d'un administrateur plateforme ;
2. **tous** les nœuds de rattachement du compte (nœud gestionnaire, nominations en cours, invitation
   acceptée) sont dans son périmètre ;
3. il **pourrait nommer** à chacun des offices en cours du compte (règle `appointed_by` du
   catalogue) : un chancelier ne gère pas l'évêque, un curé ne gère pas un vicaire (nommé par
   l'évêque) mais gère la secrétaire ou l'économe paroissial.

Un fidèle inscrit seul (sans rattachement) relève de la plateforme. Hors périmètre, la fiche répond
**404** (on ne révèle pas l'existence du compte). Les attributions d'offices passent par
`assignment_create` / `assignment_terminate` (autorité de nomination déjà contrôlée).

## 4. Application → Keycloak

| Action | Ordre | Si Keycloak échoue |
|---|---|---|
| Création | Keycloak d'abord (identifiant), puis base | Rien en base ; si la base échoue ensuite, le compte Keycloak est **supprimé** (compensation). E-mail existant dans Keycloak et inconnu de l'application : rattaché (idempotent), pas d'invitation. |
| Modification, (dés)activation, rôle plateforme, e-mail vérifié | Base puis Keycloak, même transaction | Exception → transaction annulée |
| Suppression (RGPD) | Anonymisation (`account_erase`) puis `DELETE` Keycloak, même transaction | Anonymisation annulée |
| Profil modifié par la personne | Tâche `keycloak_account_push_task` après validation (réessayée) | Réessais ; la réconciliation rattrape |
| Suppression par la personne | Inchangé (tâche différée `keycloak_user_delete_task`) | Réessais |

Invitation : Keycloak envoie lui-même l'e-mail `execute-actions-email` (`VERIFY_EMAIL`,
`UPDATE_PASSWORD`, lien valable 72 h, `KEYCLOAK_ACTIONS_EMAIL_LIFESPAN`). L'admin Django ne peut plus
créer ni supprimer de compte ; e-mail et état y sont en lecture seule.

## 5. Keycloak → application

Le Keycloak partagé est l'image officielle **sans SPI** : la synchronisation lit donc les événements
par l'**Admin REST API**.

- `keycloak_events_poll_task` (Beat, chaque minute) : `GET /events` et `GET /admin-events` depuis un
  curseur par flux (relecture d'une minute de chevauchement, dédoublonnage sur l'identifiant de
  l'événement). Événements retenus : `REGISTER`, `UPDATE_EMAIL`, `VERIFY_EMAIL`, `UPDATE_PROFILE`,
  `DELETE_ACCOUNT`, `UPDATE_TOTP`, `REMOVE_TOTP` et les événements admin `USER`,
  `REALM_ROLE_MAPPING`, `GROUP_MEMBERSHIP`. Chaque compte concerné est relu une fois par passe
  (`account_pull`). Un flux injoignable garde son curseur ; un événement en échec est retraité
  (10 tentatives).
- `account_pull` : Keycloak fait foi pour e-mail, prénom, nom, activé, e-mail vérifié, rôle
  `platform_admin`. Compte inconnu : rattaché si l'e-mail est **vérifié** dans Keycloak et le compte
  local non lié, sinon créé ; jamais de rattachement d'une adresse non vérifiée (écart
  `conflit_email`). Compte supprimé dans Keycloak : effacé (RGPD) côté application, sauf nomination
  en cours (compte désactivé, écart `supprime_avec_nominations` à traiter par l'autorité).
- **Réconciliation** `keycloak_accounts_reconcile_task` (chaque heure) et
  `manage.py sync_keycloak [--dry-run] [--json]` : compare les deux annuaires, corrige
  (`keycloak_seul` → lier/créer ; `application_seule` → créer dans Keycloak ; `champs_differents` →
  aligner ; `supprime_dans_keycloak` → absence confirmée compte par compte puis effacement, au plus
  `KEYCLOAK_RECONCILE_MAX_DELETIONS` = 5 par passe, sinon rien n'est effacé et l'écart est signalé).
  Rapport archivé (`KeycloakSyncRun`, e-mails masqués).
- **Option webhook** (`POST /api/v1/integrations/keycloak/events/`) : pour un Keycloak équipé du SPI
  p2-inc `keycloak-events`. **Désactivée par défaut** (`KEYCLOAK_WEBHOOK_ENABLED=false`, réponse 404).
  Signature : en-tête `X-Keycloak-Signature` = HMAC-SHA256 hexadécimal du corps avec
  `KEYCLOAK_WEBHOOK_SECRET`.

## 6. Garde-fous

- Jamais de mot de passe saisi par un administrateur : lien Keycloak seulement.
- **Pas d'usurpation d'identité** (impersonation) : refusée (accès au contenu des messages, RG-09).
- Motif obligatoire (journalisé) : désactivation, suppression, réinitialisation du second facteur,
  e-mail marqué vérifié, rôle plateforme. Suppression : l'e-mail du compte est recopié.
- Pas d'action destructive sur son propre compte ; jamais de retrait (ni désactivation, ni
  suppression) du **dernier** administrateur plateforme.
- Réservé à la plateforme : rôle `platform_admin`, e-mail marqué vérifié sans lien, réconciliation
  manuelle, état de la synchronisation. Les rôles `fidele`/`staff` ne se donnent pas à la main
  (`staff` suit les nominations).
- Suppression refusée tant qu'une nomination est en cours. Export CSV protégé contre l'injection de
  formules, journalisé.
- Journal : toutes les actions `compte.admin.*` (qui, quoi, quand, sur qui, nœud, motif) dans
  `AuditEvent`, IP tronquée.

## 7. Routes (`/api/v1/`)

| Méthode | Route | Rôle |
|---|---|---|
| GET | `admin/scope/` | Mon périmètre (plateforme ?, nœuds, actions requises proposées, `impersonation: false`) |
| GET | `admin/dashboard/` | Compteurs : total, actifs, en attente, désactivés, responsables, admins plateforme, créés 30 j, non liés, écarts, invitations en attente ; dernière réconciliation |
| GET / POST | `admin/accounts/` | Liste (filtres `q`, `status`, `role`, `sync`, `etat_de_vie`, `node`, `created_from/to`, `ordering`, pagination) / création (+ invitation) |
| GET | `admin/accounts/export/` | CSV (mêmes filtres) |
| GET / PATCH / DELETE | `admin/accounts/{id}/` | Fiche (+ état Keycloak en direct : sessions, OTP, rôles, groupes, blocage) / modification / suppression RGPD (`confirm_email`, `reason`) |
| POST | `admin/accounts/{id}/disable/` · `enable/` | Désactiver (motif) · réactiver (+ déblocage force brute) |
| POST | `admin/accounts/{id}/password-reset/` · `actions-email/` | Lien nouveau mot de passe · e-mail d'actions requises |
| POST | `admin/accounts/{id}/verify-email/` · `mark-email-verified/` | Renvoyer la vérification · marquer vérifié (plateforme) |
| GET / POST / DELETE | `admin/accounts/{id}/sessions/` · `logout/` · `sessions/{sid}/` | Sessions · tout fermer · fermer une session |
| POST | `admin/accounts/{id}/otp-reset/` · `brute-force-unlock/` | Second facteur réinitialisé · déblocage |
| POST | `admin/accounts/{id}/platform-admin/` | Rôle plateforme (`grant`, `reason`) |
| POST | `admin/accounts/{id}/resync/` | Relire / pousser le compte |
| POST | `admin/accounts/{id}/offices/` · `offices/{aid}/end/` | Nommer · mettre fin |
| GET | `admin/audit/` | Journal des actions sur les comptes (filtres `account`, `actor`, `action`, dates) |
| GET | `admin/sync/` | État : non liés, écarts par type, curseurs, événements, 10 dernières réconciliations (plateforme) |
| POST / GET | `admin/sync/runs/` · `sync/runs/{id}/` | Lancer (simulation par défaut) · rapport (plateforme) |
| POST | `integrations/keycloak/events/` | Webhook SPI (option désactivée) |

Erreurs : format V1 `{"error": {code, message, details}}` ; `503 keycloak_unavailable` = rien n'a été
modifié ; `409 account_exists | account_not_linked | active_office | last_platform_admin |
keycloak_conflict` ; `403 account_above_scope | account_out_of_scope | account_platform_scope |
node_out_of_scope | platform_only | self_action`.

## 8. Configuration côté serveur Keycloak

1. Client confidentiel `jangubi-admin-sync`, *Service accounts* activé, rôles de client
   `realm-management` : `view-users`, `manage-users`, `query-users`, `view-realm`, `view-events`
   (déjà dans `infra/keycloak/realm-jangubi.json`). Secret → `KEYCLOAK_ADMIN_CLIENT_SECRET`.
2. Realm → *Events* : *Save events* et *Save admin events* (avec détails) activés, expiration 90 jours.
3. SMTP du realm configuré (Keycloak envoie les e-mails d'actions requises) ; *Brute force detection*
   activée ; action requise `CONFIGURE_TOTP` activée.
4. Variables : `KEYCLOAK_REALM` (`jangubi-staging` en recette, `jangubi` en production),
   `KEYCLOAK_INTERNAL_URL`, `KEYCLOAK_ADMIN_BACKEND=http`, `KEYCLOAK_ACTIONS_CLIENT_ID` /
   `KEYCLOAK_ACTIONS_REDIRECT_URI` (retour vers le web après l'e-mail, facultatif),
   `KEYCLOAK_RECONCILE_MAX_DELETIONS`, `KEYCLOAK_EVENTS_POLL_ENABLED`.
5. Aucun SPI requis. Option webhook : SPI p2-inc `keycloak-events` + `KEYCLOAK_WEBHOOK_ENABLED=true`
   + `KEYCLOAK_WEBHOOK_SECRET`.
6. Premier déploiement : `manage.py sync_keycloak --dry-run`, lire le rapport, puis
   `manage.py sync_keycloak`.
