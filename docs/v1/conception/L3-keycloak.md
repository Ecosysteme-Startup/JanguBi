# L3 — Authentification Keycloak

> Conception du lot L3 (plan §2 L3 ; SRS §3.3 ; ADR-004). Version du 25/09/2026.

## 1. Principe

Keycloak dit **qui** est connecté ; l'application dit **ce qu'il peut faire, où** (L2). Trois rôles de realm seulement : `fidele` (défaut), `staff`, `platform_admin`. Aucun groupe ni rôle ecclésial dans Keycloak.

## 2. Realm `jangubi` (versionné : `infra/keycloak/realm-jangubi.json`)

| Élément | Réglage |
|---|---|
| Client `jangubi-web` | public, Authorization Code + **PKCE S256**, pas de flux implicite ni direct grant ; redirection **exacte** vers le rappel Auth.js (`/api/auth/callback/keycloak`, jamais de joker) ; mapper d'audience ajoutant `jangubi-api` à `aud` ; mapper `amr` |
| Client `jangubi-mobile` (V2, 27/09/2026) | app iOS et Android : public, Authorization Code + **PKCE S256** dans le navigateur système (RFC 8252), pas de flux implicite ni direct grant ; redirection **exacte** `sn.numerisen.jangubi://oauth` (`KC_MOBILE_REDIRECT_URI`) ; mêmes mappers (audience `jangubi-api`, `amr`, téléphone, date de naissance) ; ajouté à `KEYCLOAK_ALLOWED_CLIENTS` (claim `azp`) |
| Client `jangubi-api` | bearer-only (aucune connexion) : c'est l'**audience** attendue par l'API |
| Client `jangubi-admin-sync` | confidentiel, compte de service seulement, rôles `realm-management` : `view-users`, `manage-users`, `view-realm` (synchronisation du rôle `staff`, migration des comptes) |
| Rôles | `fidele` (rôle par défaut), `staff`, `platform_admin` |
| MFA | politique TOTP (6 chiffres, 30 s) ; flux navigateur `browser-mfa` : OTP conditionnel, **toujours exigé** pour les rôles `staff` et `platform_admin` ; références `amr` : `pwd`, `otp` |
| Sécurité | brute force activé, vérification de l'e-mail, mot de passe ≥ 10 caractères, jetons d'accès de 10 min (ENF-02), SSO 12 h, journal des connexions et des actions d'administration (90 jours) |
| Secrets | **aucune valeur par défaut** pour le secret de `jangubi-admin-sync` (il peut attribuer des rôles) : `make kc-up` refuse de démarrer sans `KEYCLOAK_ADMIN_CLIENT_SECRET` |

## 3. API (DRF)

`apps/authentication/keycloak.py` :

- `KeycloakJWTAuthentication` : `Authorization: Bearer <jwt>`. Le jeton est reconnu comme Keycloak si son `iss` est celui du realm ; sinon la classe s'efface (retour `None`) et l'ancienne authentification SimpleJWT peut prendre la main **tant que `LEGACY_JWT_ENABLED` est vrai**. Un jeton Keycloak invalide (signature, `exp`, `iss`, `aud`, `azp`) → 401, jamais de repli.
- JWKS : récupéré sur `…/protocol/openid-connect/certs`, mis en cache (cache Django = Redis en production, 1 h) ; un `kid` inconnu force **un** rechargement (rotation des clés), limité à un par minute.
- Provisioning (EF-AUTH-02) : par `sub` ; à défaut, rattachement d'un compte existant par e-mail **vérifié** (comptes migrés) ; sinon création d'un fidèle. Idempotent.
- Rôles de realm portés sur l'utilisateur de la requête : `authz.is_platform_admin` lit `platform_admin` quand la requête vient de Keycloak (le super-admin legacy reste reconnu tant que `LEGACY_JWT_ENABLED`).
- **MFA côté API** (EF-AUTH-05) : toute permission par capacité (`HasCapability`, écritures `hierarchy`) exige, pour un jeton Keycloak, `amr ∋ otp` (ou `acr` dans `KEYCLOAK_MFA_ACR_VALUES`). Sinon 403 `mfa_required`. Désactivable par réglage pour le développement.

## 4. WebSocket (EF-AUTH-03)

Les navigateurs ne posent pas d'en-tête sur une WebSocket. Pour ne pas mettre le jeton d'accès (valable sur toute l'API) dans l'URL, où il finit dans les journaux, le client échange son jeton contre un **ticket à usage unique de 60 s** (`POST /api/v1/me/ws-ticket/`) et ouvre `/ws/...?ticket=<ticket>`. `?token=<jwt>` reste accepté pendant la transition (même validation que l'API). Ticket ou jeton invalide → fermeture **4401** avant tout traitement.

## 5. Synchronisation du rôle `staff` (EF-AUTH-04)

Toute création, fin ou annulation de nomination, et la tâche quotidienne, déclenchent `keycloak_staff_sync_task(person_id)` après commit : rôle `staff` ajouté s'il existe une nomination active, retiré sinon ; à l'ajout, l'action requise `CONFIGURE_TOTP` est posée. Réconciliation complète chaque nuit. `platform_admin` reste géré à la main dans Keycloak.

## 6. Migration des comptes (EF-AUTH-06)

`manage.py migrate_users_to_keycloak [--apply]` : simulation par défaut. Les hachages `pbkdf2_sha256$<itérations>$<sel>$<hash>` de Django sont importés tels quels (credential Keycloak `pbkdf2-sha256`, sel encodé en base64) : aucun mot de passe à réinitialiser. Les comptes sans mot de passe utilisable ou avec un autre algorithme reçoivent l'action requise `UPDATE_PASSWORD`. Le `sub` Keycloak est enregistré dans `BaseUser.keycloak_sub`.

Avant `--apply` en production : auditer les comptes `is_verified=True` (le drapeau est repris tel quel dans Keycloak, et un e-mail vérifié permet le rattachement automatique d'un compte).

## 7. Bascule et retrait de SimpleJWT

La bascule est un **réglage**, pas un déploiement de code : `KEYCLOAK_ENABLED=true` active la validation Keycloak ; `LEGACY_JWT_ENABLED=false` retire SimpleJWT des classes d'authentification et coupe les routes `/api/v1/auth/jwt/*`. Les deux coexistent pendant la transition du front (Auth.js), ce qui évite de casser le front déployé. `jwt_key` reste en base jusqu'en L9 (contract).

## 8. Tests

Clé RSA de test et JWKS local servis par un faux client HTTP (aucun Keycloak en CI) : jeton valide, expiré, mauvais `iss`/`aud`/`azp`, `kid` inconnu puis rotation, provisioning idempotent et rattachement par e-mail vérifié, MFA exigée pour les endpoints à capacité, WebSocket 4401, synchronisation du rôle `staff` (client d'admin simulé), conversion des hachages. Test d'intégration optionnel `-m keycloak` contre le conteneur (`make kc-up`).
