"""Intégration contre un vrai Keycloak (``make kc-up``), hors CI.

    KEYCLOAK_E2E_URL=http://localhost:8180 KEYCLOAK_E2E_ADMIN_PASSWORD=admin \
    KEYCLOAK_E2E_SYNC_SECRET=dev-only-change-me pytest -m keycloak apps/authentication
"""

import os
import uuid

import httpx
import pytest
from django.contrib.auth.hashers import PBKDF2PasswordHasher
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from apps.authentication.keycloak_admin import KeycloakAdmin, django_hash_to_keycloak_credential
from apps.authentication.services_keycloak import keycloak_staff_role_sync
from apps.hierarchy.tests.factories import Tree, make_node, nominate

KC = os.environ.get("KEYCLOAK_E2E_URL", "")
pytestmark = [
    pytest.mark.keycloak,
    pytest.mark.django_db,
    pytest.mark.skipif(not KC, reason="KEYCLOAK_E2E_URL non défini (Keycloak réel requis)"),
]
REALM = "jangubi"


def _admin_token() -> str:
    response = httpx.post(
        f"{KC}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": os.environ.get("KEYCLOAK_E2E_ADMIN_USER", "admin"),
            "password": os.environ.get("KEYCLOAK_E2E_ADMIN_PASSWORD", "admin"),
        },
    )
    response.raise_for_status()
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def direct_grant_client():
    """Client de test à mot de passe direct, créé pour le test puis supprimé."""
    headers = {"Authorization": f"Bearer {_admin_token()}"}
    client_id = f"e2e-{uuid.uuid4().hex[:8]}"
    rep = {
        "clientId": client_id,
        "publicClient": True,
        "directAccessGrantsEnabled": True,
        "standardFlowEnabled": False,
        "protocolMappers": [
            {
                "name": "aud",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "config": {"included.client.audience": "jangubi-api", "access.token.claim": "true"},
            }
        ],
    }
    response = httpx.post(f"{KC}/admin/realms/{REALM}/clients", json=rep, headers=headers)
    internal_id = response.headers["Location"].rsplit("/", 1)[-1]
    yield client_id
    httpx.delete(f"{KC}/admin/realms/{REALM}/clients/{internal_id}", headers={"Authorization": f"Bearer {_admin_token()}"})


@pytest.fixture
def kc_settings(direct_grant_client):
    cache.clear()
    with override_settings(
        KEYCLOAK_ENABLED=True,
        KEYCLOAK_ISSUER=f"{KC}/realms/{REALM}",
        KEYCLOAK_JWKS_URL=f"{KC}/realms/{REALM}/protocol/openid-connect/certs",
        KEYCLOAK_INTERNAL_URL=KC,
        KEYCLOAK_ALLOWED_CLIENTS=["jangubi-web", direct_grant_client],
        KEYCLOAK_ADMIN_CLIENT_SECRET=os.environ.get("KEYCLOAK_E2E_SYNC_SECRET", "dev-only-change-me"),
        KEYCLOAK_REQUIRE_MFA_FOR_STAFF=False,
    ):
        yield direct_grant_client


def test_imported_django_hash_logs_in_and_the_api_provisions_the_person(kc_settings):
    tree = Tree()
    email = f"pretre-{uuid.uuid4().hex[:6]}@e2e.sn"
    encoded = PBKDF2PasswordHasher().encode("MotDePasse-2026!", "selDjango123", iterations=600_000)
    admin = KeycloakAdmin()
    keycloak_id, created = admin.user_create(
        {
            "username": email,
            "email": email,
            "emailVerified": True,
            "enabled": True,
            "firstName": "Jean",
            "lastName": "Diouf",
            "credentials": [django_hash_to_keycloak_credential(encoded)],
        }
    )
    assert created

    token = httpx.post(
        f"{KC}/realms/{REALM}/protocol/openid-connect/token",
        data={"grant_type": "password", "client_id": kc_settings, "username": email, "password": "MotDePasse-2026!"},
    ).json()["access_token"]

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    response = client.get("/api/v1/me/capacites/")
    assert response.status_code == 200

    from django.contrib.auth import get_user_model

    person = get_user_model().objects.get(keycloak_sub=keycloak_id)
    assert person.email == email

    # Rôle staff synchronisé par la nomination, retiré à la fin.
    person.degre_ordre = "pretre"
    person.statut_verification = "verifie"
    person.save()
    parish = make_node("ceb", "CEB e2e", tree.saint_dominique)
    assignment = nominate(person, "responsable_ceb", parish)
    assert keycloak_staff_role_sync(person=person) == "added"
    assert "staff" in admin.user_realm_roles(keycloak_id)
    assignment.status = "terminee"
    assignment.save()
    assert keycloak_staff_role_sync(person=person) == "removed"

    httpx.delete(f"{KC}/admin/realms/{REALM}/users/{keycloak_id}", headers={"Authorization": f"Bearer {_admin_token()}"})
