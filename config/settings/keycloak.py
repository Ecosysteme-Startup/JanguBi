"""Authentification Keycloak (ADR-004, lot L3).

Keycloak est la seule authentification de l'API et du WebSocket (bascule du 25/09/2026 :
SimpleJWT et les parcours d'inscription, d'activation, de mot de passe et d'e-mail maison
sont retirés ; ils relèvent de Keycloak). KEYCLOAK_ENABLED ne commande plus que la
synchronisation avec l'API d'administration Keycloak (rôle staff, suppression de compte).
"""

from config.env import env

KEYCLOAK_ENABLED = env.bool("KEYCLOAK_ENABLED", default=True)

KEYCLOAK_SERVER_URL = env.str("KEYCLOAK_SERVER_URL", default="http://localhost:8180").rstrip("/")
# URL interne (conteneur → conteneur) pour le JWKS et l'API d'administration ; l'émetteur
# (iss) reste l'URL publique vue par le navigateur.
KEYCLOAK_INTERNAL_URL = env.str("KEYCLOAK_INTERNAL_URL", default=KEYCLOAK_SERVER_URL).rstrip("/")
KEYCLOAK_REALM = env.str("KEYCLOAK_REALM", default="jangubi")
KEYCLOAK_ISSUER = env.str("KEYCLOAK_ISSUER", default=f"{KEYCLOAK_SERVER_URL}/realms/{KEYCLOAK_REALM}")
KEYCLOAK_JWKS_URL = env.str(
    "KEYCLOAK_JWKS_URL", default=f"{KEYCLOAK_INTERNAL_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"
)
KEYCLOAK_AUDIENCE = env.str("KEYCLOAK_AUDIENCE", default="jangubi-api")
# Clients dont l'API accepte les jetons (claim ``azp``) : le web (Auth.js) et l'app mobile (PKCE natif).
KEYCLOAK_ALLOWED_CLIENTS = env.list("KEYCLOAK_ALLOWED_CLIENTS", default=["jangubi-web", "jangubi-mobile"])
KEYCLOAK_JWKS_CACHE_SECONDS = env.int("KEYCLOAK_JWKS_CACHE_SECONDS", default=3600)
KEYCLOAK_LEEWAY_SECONDS = env.int("KEYCLOAK_LEEWAY_SECONDS", default=30)

# MFA exigée côté API pour les endpoints à capacité (défense en profondeur, EF-AUTH-05).
KEYCLOAK_REQUIRE_MFA_FOR_STAFF = env.bool("KEYCLOAK_REQUIRE_MFA_FOR_STAFF", default=True)
KEYCLOAK_MFA_AMR_VALUES = env.list("KEYCLOAK_MFA_AMR_VALUES", default=["otp", "mfa"])
KEYCLOAK_MFA_ACR_VALUES = env.list("KEYCLOAK_MFA_ACR_VALUES", default=["gold", "2"])

# Compte de service pour l'API d'administration (synchronisation du rôle staff, migration).
KEYCLOAK_ADMIN_CLIENT_ID = env.str("KEYCLOAK_ADMIN_CLIENT_ID", default="jangubi-admin-sync")
KEYCLOAK_ADMIN_CLIENT_SECRET = env.str("KEYCLOAK_ADMIN_CLIENT_SECRET", default="")
KEYCLOAK_STAFF_ROLE = "staff"
KEYCLOAK_PLATFORM_ADMIN_ROLE = "platform_admin"

# --- Administration des comptes (docs/ADMIN-KEYCLOAK.md) ------------------------------------
# "http" (API d'administration réelle), "fake" (en mémoire : tests, développement hors ligne)
# ou chemin d'import d'une fabrique.
KEYCLOAK_ADMIN_BACKEND = env.str("KEYCLOAK_ADMIN_BACKEND", default="http")
KEYCLOAK_ADMIN_TIMEOUT_SECONDS = env.float("KEYCLOAK_ADMIN_TIMEOUT_SECONDS", default=10.0)
KEYCLOAK_ADMIN_CONNECT_TIMEOUT_SECONDS = env.float("KEYCLOAK_ADMIN_CONNECT_TIMEOUT_SECONDS", default=3.0)
# Sync Keycloak → application : lecture périodique des événements par l'Admin REST API (le
# Keycloak partagé est l'image officielle, sans SPI). « Save events » et « Save admin events »
# doivent être activés sur le realm (conservation 90 jours).
KEYCLOAK_EVENTS_POLL_ENABLED = env.bool("KEYCLOAK_EVENTS_POLL_ENABLED", default=True)
# Première lecture (pas de curseur) : on remonte au plus loin de cette durée ; la réconciliation
# complète rattrape le reste.
KEYCLOAK_EVENTS_INITIAL_LOOKBACK_HOURS = env.int("KEYCLOAK_EVENTS_INITIAL_LOOKBACK_HOURS", default=24)
KEYCLOAK_EVENTS_MAX_PER_POLL = env.int("KEYCLOAK_EVENTS_MAX_PER_POLL", default=2000)
# Option : webhook d'un SPI d'événements (p2-inc keycloak-events), DÉSACTIVÉ par défaut.
KEYCLOAK_WEBHOOK_ENABLED = env.bool("KEYCLOAK_WEBHOOK_ENABLED", default=False)
# Secret partagé avec le SPI : signature HMAC-SHA256 du corps.
KEYCLOAK_WEBHOOK_SECRET = env.str("KEYCLOAK_WEBHOOK_SECRET", default="")
# Garde-fou de la réconciliation : au-delà, aucune anonymisation automatique (realm mal configuré ?).
KEYCLOAK_RECONCILE_MAX_DELETIONS = env.int("KEYCLOAK_RECONCILE_MAX_DELETIONS", default=5)
# Durée de validité du lien envoyé par Keycloak (actions requises), en secondes (72 h).
KEYCLOAK_ACTIONS_EMAIL_LIFESPAN = env.int("KEYCLOAK_ACTIONS_EMAIL_LIFESPAN", default=72 * 3600)
KEYCLOAK_ACTIONS_CLIENT_ID = env.str("KEYCLOAK_ACTIONS_CLIENT_ID", default="jangubi-web")
KEYCLOAK_ACTIONS_REDIRECT_URI = env.str("KEYCLOAK_ACTIONS_REDIRECT_URI", default="")
