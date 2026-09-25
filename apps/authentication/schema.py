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


class LegacyJwtScheme(OpenApiAuthenticationExtension):
    target_class = "apps.authentication.authentication.JwtKeyEnforcingJWTAuthentication"
    name = "legacyJwt"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "bearerFormat": "JWT", "description": "Ancien JWT (transition)."}


class SessionScheme(OpenApiAuthenticationExtension):
    target_class = "apps.api.mixins.CsrfExemptedSessionAuthentication"
    name = "session"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "cookie", "name": "sessionid"}


class SessionHeaderScheme(OpenApiAuthenticationExtension):
    target_class = "apps.api.mixins.SessionAsHeaderAuthentication"
    name = "sessionHeader"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "header", "name": "Authorization"}
