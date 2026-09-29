"""Client de l'API d'administration Keycloak (compte de service ``jangubi-admin-sync``).

``get_keycloak_admin()`` renvoie le client HTTP réel, ou le faux client en mémoire
(``KEYCLOAK_ADMIN_BACKEND = "fake"``, utilisé par les tests et le développement hors ligne).
"""

from apps.integrations.keycloak.client import KeycloakAdminClient, get_keycloak_admin

__all__ = ["KeycloakAdminClient", "get_keycloak_admin"]
