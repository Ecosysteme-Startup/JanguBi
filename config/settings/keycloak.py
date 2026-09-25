"""Authentification Keycloak (ADR-004, lot L3).

La bascule est un réglage : KEYCLOAK_ENABLED active la validation des jetons
Keycloak ; LEGACY_JWT_ENABLED garde SimpleJWT pendant la transition du front.
"""

from config.env import env

KEYCLOAK_ENABLED = env.bool("KEYCLOAK_ENABLED", default=False)
LEGACY_JWT_ENABLED = env.bool("LEGACY_JWT_ENABLED", default=True)

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
KEYCLOAK_ALLOWED_CLIENTS = env.list("KEYCLOAK_ALLOWED_CLIENTS", default=["jangubi-web"])
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
