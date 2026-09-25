"""Authentification Keycloak sans Keycloak : clé RSA et JWKS locaux (EF-AUTH-01 à -06)."""

import base64
import hashlib
import json
import time
import uuid

import jwt
import pytest
from channels.testing import WebsocketCommunicator
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import PBKDF2PasswordHasher
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from apps.authentication import keycloak
from apps.authentication.keycloak_admin import django_hash_to_keycloak_credential
from apps.authentication.services_keycloak import keycloak_staff_role_sync, users_to_keycloak_migrate
from apps.hierarchy import authz
from apps.hierarchy.tests.factories import Tree, nominate, person
from apps.users.tests.factories import BaseUserFactory, SuperAdminFactory

ISSUER = "https://auth.test/realms/jangubi"

pytestmark = pytest.mark.django_db


class Keys:
    def __init__(self) -> None:
        self.kid = "kid-1"
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.published: list[dict] = [self.jwk(self.private, self.kid)]

    @staticmethod
    def jwk(private, kid: str) -> dict:
        data = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
        return {**data, "kid": kid, "use": "sig", "alg": "RS256"}

    def token(self, **overrides) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": ["jangubi-api", "account"],
            "azp": "jangubi-web",
            "typ": "Bearer",
            "sub": overrides.pop("sub", str(uuid.uuid4())),
            "iat": now,
            "exp": now + 300,
            "email": "fidele@test.sn",
            "email_verified": True,
            "given_name": "Awa",
            "family_name": "Ndiaye",
            "realm_access": {"roles": ["fidele"]},
            **overrides,
        }
        claims = {k: v for k, v in claims.items() if v is not None}
        kid = overrides.get("_kid", self.kid)
        claims.pop("_kid", None)
        return jwt.encode(claims, self.private, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def keys(monkeypatch):
    cache.clear()
    k = Keys()
    monkeypatch.setattr(keycloak, "_jwks_fetch", lambda: {"keys": list(k.published)})
    with override_settings(
        KEYCLOAK_ENABLED=True,
        KEYCLOAK_ISSUER=ISSUER,
        KEYCLOAK_AUDIENCE="jangubi-api",
        KEYCLOAK_ALLOWED_CLIENTS=["jangubi-web"],
        KEYCLOAK_REQUIRE_MFA_FOR_STAFF=True,
    ):
        yield k
    cache.clear()


def api(token: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


ME = "/api/v1/me/capacites/"


# --- Validation (EF-AUTH-01) --------------------------------------------------------------


def test_valid_token_authenticates_and_provisions_once(keys):
    sub = str(uuid.uuid4())
    token = keys.token(sub=sub, email="awa@test.sn")

    assert api(token).get(ME).status_code == 200
    assert api(token).get(ME).status_code == 200

    user = get_user_model().objects.get(keycloak_sub=sub)
    assert (user.email, user.is_active, user.is_verified, user.phone_number) == ("awa@test.sn", True, True, None)
    assert user.profile.first_name == "Awa"
    assert get_user_model().objects.filter(email="awa@test.sn").count() == 1


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200}, "expiré"),
        ({"aud": ["autre-api"]}, "audience"),
        ({"azp": "client-pirate"}, "client"),
        ({"typ": "Refresh"}, "type"),
        ({"azp": None}, "client absent"),
    ],
)
def test_invalid_keycloak_tokens_are_401(keys, overrides, reason):
    response = api(keys.token(**overrides)).get(ME)
    assert response.status_code == 401, reason


def test_foreign_issuer_is_not_trusted(keys):
    """Autre émetteur : ce n'est pas un jeton Keycloak ; l'ancien JWT le refuse aussi."""
    assert api(keys.token(iss="https://pirate.test/realms/jangubi")).get(ME).status_code == 401


def test_forged_signature_is_401(keys):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(
        {"iss": ISSUER, "aud": "jangubi-api", "sub": "x", "iat": int(time.time()), "exp": int(time.time()) + 60},
        other,
        algorithm="RS256",
        headers={"kid": keys.kid},
    )
    assert api(forged).get(ME).status_code == 401


def test_hs256_token_claiming_our_issuer_is_refused(keys):
    forged = jwt.encode(
        {"iss": ISSUER, "aud": "jangubi-api", "sub": "x", "iat": int(time.time()), "exp": int(time.time()) + 60},
        "secret-partage",
        algorithm="HS256",
        headers={"kid": keys.kid},
    )
    assert api(forged).get(ME).status_code == 401


def test_key_rotation_refreshes_the_jwks_once(keys):
    new_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": "jangubi-api",
            "azp": "jangubi-web",
            "sub": str(uuid.uuid4()),
            "email": "rotation@test.sn",
            "email_verified": True,
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
        },
        new_private,
        algorithm="RS256",
        headers={"kid": "kid-2"},
    )
    keycloak.jwks_get()  # JWKS en cache sans la nouvelle clé
    keys.published.append(Keys.jwk(new_private, "kid-2"))

    assert api(token).get(ME).status_code == 200


def test_unknown_kid_is_401(keys):
    assert api(keys.token(_kid="inconnu")).get(ME).status_code == 401


# --- Provisioning (EF-AUTH-02) -------------------------------------------------------------


def test_existing_account_is_linked_by_verified_email(keys):
    existing = BaseUserFactory.create(email="migre@test.sn")
    sub = str(uuid.uuid4())

    assert api(keys.token(sub=sub, email="migre@test.sn")).get(ME).status_code == 200

    existing.refresh_from_db()
    assert existing.keycloak_sub == sub


def test_unverified_email_never_takes_over_an_account(keys):
    BaseUserFactory.create(email="cible@test.sn")
    response = api(keys.token(email="cible@test.sn", email_verified=False)).get(ME)
    assert response.status_code == 401
    assert get_user_model().objects.get(email="cible@test.sn").keycloak_sub is None


def test_inactive_account_is_refused(keys):
    sub = str(uuid.uuid4())
    BaseUserFactory.create(email="off@test.sn", keycloak_sub=sub, is_active=False)
    assert api(keys.token(sub=sub, email="off@test.sn")).get(ME).status_code == 401


# --- Rôles et MFA (EF-AUTH-05) -----------------------------------------------------------


def _staff(keys, **claims):
    tree = Tree()
    sub = str(uuid.uuid4())
    secretary = person("secretaire@test.sn", keycloak_sub=sub)
    nominate(secretary, "secretaire_paroissial", tree.saint_dominique)
    return tree, keys.token(sub=sub, email="secretaire@test.sn", **claims)


def test_staff_endpoint_requires_mfa(keys):
    tree, token = _staff(keys)
    response = api(token).get("/api/v1/audit/")
    assert response.status_code == 403
    assert response.data["error"]["code"] == "mfa_required"


def test_staff_endpoint_with_otp_passes(keys):
    tree, token = _staff(keys, amr=["pwd", "otp"])
    nominate(get_user_model().objects.get(email="secretaire@test.sn"), "cure", tree.sainte_therese)  # audit.voir
    assert api(token).get("/api/v1/audit/").status_code == 200


def test_fidele_without_mfa_uses_basic_endpoints(keys):
    assert api(keys.token()).get(ME).status_code == 200


def test_platform_admin_comes_from_the_realm_role(keys):
    admin_token = keys.token(email="numerisen@test.sn", realm_access={"roles": ["platform_admin"]}, amr=["otp"])
    assert api(admin_token).get("/api/v1/hierarchy/capability-overrides/").status_code == 200

    legacy_super = SuperAdminFactory.create(email="ancien@test.sn", keycloak_sub="sub-ancien")
    plain = keys.token(sub="sub-ancien", email="ancien@test.sn", amr=["otp"])
    assert api(plain).get("/api/v1/hierarchy/capability-overrides/").status_code == 403
    assert legacy_super.role == "super_admin"


def test_non_keycloak_bearer_token_is_refused(keys):
    """Keycloak est la seule authentification : un ancien JWT (ou tout autre jeton) donne 401."""
    forged = jwt.encode({"user_id": str(BaseUserFactory.create().pk)}, "une-autre-cle", algorithm="HS256")
    assert api(forged).get(ME).status_code == 401


# --- WebSocket (EF-AUTH-03) --------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_websocket_closes_4401_on_invalid_ticket(keys):
    from config.asgi import application

    communicator = WebsocketCommunicator(application, "/ws/notifications/?ticket=pas-un-ticket", headers=[(b"origin", b"http://localhost:3000")])
    connected, code = await communicator.connect()
    assert not connected
    assert code == 4401
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_websocket_ignores_a_token_in_the_url(keys):
    """Le jeton ne passe jamais dans l'URL (journaux) : seul le ticket authentifie la socket."""
    from config.asgi import application

    token = keys.token(email="ws@test.sn")
    communicator = WebsocketCommunicator(application, f"/ws/notifications/?token={token}", headers=[(b"origin", b"http://localhost:3000")])
    connected, _ = await communicator.connect()
    assert not connected
    await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_websocket_single_use_ticket(keys):
    from asgiref.sync import sync_to_async

    from apps.authentication.ws_tickets import ws_ticket_issue
    from config.asgi import application

    user = await sync_to_async(BaseUserFactory.create)()
    ticket = await sync_to_async(ws_ticket_issue)(user=user)
    origin = [(b"origin", b"http://localhost:3000")]

    first = WebsocketCommunicator(application, f"/ws/notifications/?ticket={ticket}", headers=origin)
    assert (await first.connect())[0]
    await first.disconnect()

    replay = WebsocketCommunicator(application, f"/ws/notifications/?ticket={ticket}", headers=origin)
    connected, code = await replay.connect()
    assert not connected and code == 4401


def test_ws_ticket_api_requires_authentication_and_returns_a_ticket(keys):
    assert APIClient().post("/api/v1/me/ws-ticket/").status_code in (401, 403)
    response = api(keys.token(email="t@test.sn")).post("/api/v1/me/ws-ticket/")
    assert response.status_code == 200 and response.data["expires_in"] == 60 and len(response.data["ticket"]) > 30


# --- Synchronisation du rôle staff (EF-AUTH-04) -------------------------------------------


class FakeAdmin:
    def __init__(self) -> None:
        self.roles: dict[str, set[str]] = {}
        self.actions: dict[str, set[str]] = {}

    def user_realm_roles(self, user_id):
        return set(self.roles.get(user_id, set()))

    def add_realm_role(self, user_id, name):
        self.roles.setdefault(user_id, set()).add(name)

    def remove_realm_role(self, user_id, name):
        self.roles.get(user_id, set()).discard(name)

    def user_has_otp(self, user_id):
        return False

    def add_required_action(self, user_id, action):
        self.actions.setdefault(user_id, set()).add(action)


def test_staff_role_follows_active_assignments(keys):
    tree = Tree()
    secretary = person(keycloak_sub="kc-sec")
    admin = FakeAdmin()

    assert keycloak_staff_role_sync(person=secretary, admin=admin) == "unchanged"
    assignment = nominate(secretary, "secretaire_paroissial", tree.saint_dominique)
    assert keycloak_staff_role_sync(person=secretary, admin=admin) == "added"
    assert admin.roles["kc-sec"] == {"staff"} and admin.actions["kc-sec"] == {"CONFIGURE_TOTP"}

    assignment.status = "terminee"
    assignment.save()
    authz.invalidate_user(secretary.pk)
    assert keycloak_staff_role_sync(person=secretary, admin=admin) == "removed"


def test_staff_sync_skips_unlinked_people(keys):
    assert keycloak_staff_role_sync(person=person(), admin=FakeAdmin()) == "skipped"


# --- Migration des comptes (EF-AUTH-06) --------------------------------------------------


def test_django_pbkdf2_hash_is_converted_for_keycloak():
    encoded = PBKDF2PasswordHasher().encode("MotDePasse-2026!", "sel123", iterations=1000)
    credential = django_hash_to_keycloak_credential(encoded)

    data, secret = json.loads(credential["credentialData"]), json.loads(credential["secretData"])
    assert data == {"hashIterations": 1000, "algorithm": "pbkdf2-sha256", "additionalParameters": {}}
    assert base64.b64decode(secret["salt"]) == b"sel123"
    expected = hashlib.pbkdf2_hmac("sha256", b"MotDePasse-2026!", b"sel123", 1000)
    assert base64.b64decode(secret["value"]) == expected


@pytest.mark.parametrize("encoded", ["md5$sel$abc", "!unusable", "", "argon2$argon2id$v=19$m=1,t=1,p=1$abc$def"])
def test_other_hashes_require_a_reset(encoded):
    assert django_hash_to_keycloak_credential(encoded) is None


def test_account_migration_simulation_then_apply():
    migrated = BaseUserFactory.create(email="a@test.sn")
    BaseUserFactory.create(email="b@test.sn", keycloak_sub="deja")
    BaseUserFactory.create(email="c@test.sn", is_active=False, is_verified=False)

    simulated = {line.email: line.action for line in users_to_keycloak_migrate()}
    assert simulated == {"a@test.sn": "creer", "b@test.sn": "deja_lie", "c@test.sn": "ignorer"}
    assert get_user_model().objects.get(pk=migrated.pk).keycloak_sub is None

    class Admin:
        created: list = []

        def user_create(self, rep):
            self.created.append(rep)
            return "kc-" + rep["email"], True

    admin = Admin()
    with override_settings(KEYCLOAK_ENABLED=True):
        users_to_keycloak_migrate(apply=True, admin=admin)
    assert get_user_model().objects.get(pk=migrated.pk).keycloak_sub == "kc-a@test.sn"
    assert [r["email"] for r in admin.created] == ["a@test.sn"]
    # MD5 en tests : le mot de passe ne peut pas être importé → réinitialisation exigée.
    assert admin.created[0]["requiredActions"] == ["UPDATE_PASSWORD"]
