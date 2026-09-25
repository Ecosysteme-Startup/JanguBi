"""Déclaration OpenAPI des schémas d'authentification (drf-spectacular)."""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class KeycloakBearerScheme(OpenApiAuthenticationExtension):
    target_class = "apps.authentication.keycloak.KeycloakJWTAuthentication"
    name = "keycloakBearer"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Jeton d'accès Keycloak (realm jangubi, audience jangubi-api).",
        }
