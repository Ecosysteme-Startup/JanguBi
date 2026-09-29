"""Invitations et validation des comptes du clergé (lot V1-routes)."""

import datetime
from urllib.parse import parse_qs, urlparse

import pytest
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.hierarchy.models import AuditEvent
from apps.hierarchy.tests.factories import nominate, person, priest
from apps.invitations.models import ClergyInvitation
from apps.users.tests.factories import BaseUserFactory, SuperAdminFactory

pytestmark = pytest.mark.django_db
BASE = "/api/v1/clergy-accounts/"


def client_for(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


@pytest.fixture(autouse=True)
def _cache():
    cache.clear()


@pytest.fixture
def world(tree):
    tree.chancelier = person("chancelier@dakar.sn")
    tree.chancelier_thies = person("chancelier@thies.sn")
    tree.cure = priest("cure@sd.sn")
    nominate(tree.chancelier, "chancelier", tree.dakar)
    nominate(tree.chancelier_thies, "chancelier", tree.thies)
    nominate(tree.cure, "cure", tree.saint_dominique)
    return tree


def invite(world, actor=None, **kw):
    payload = {
        "node": str(world.saint_dominique.pk),
        "email": "Emmanuel.Tine@Test.sn",
        "first_name": "Emmanuel",
        "last_name": "Tine",
        "etat_de_vie": "clerc",
        "degre_ordre": "pretre",
        **kw,
    }
    return client_for(actor or world.chancelier).post(f"{BASE}invitations/", payload, format="json")


def token_of(response) -> str:
    return parse_qs(urlparse(response.json()["accept_url"]).query)["token"][0]


def test_full_cycle_invite_accept_validate(world, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        created = invite(world)
    assert created.status_code == 201, created.content
    token = token_of(created)
    assert created.json()["status"] == "en_attente"
    assert len(mail.outbox) == 1 and token in mail.outbox[0].body
    stored = ClergyInvitation.objects.get()
    assert stored.email == "emmanuel.tine@test.sn" and token not in stored.token_hash

    public = client_for().post(f"{BASE}invitations/validate/", {"token": token}, format="json")
    assert public.status_code == 200
    assert public.json()["email_masked"].endswith("@test.sn") and "emmanuel" not in public.json()["email_masked"]
    assert "/protocol/openid-connect/registrations?" in public.json()["register_url"]

    newcomer = BaseUserFactory(email="emmanuel.tine@test.sn")
    accepted = client_for(newcomer).post(f"{BASE}invitations/accept/", {"token": token}, format="json")
    assert accepted.status_code == 200, accepted.content
    assert accepted.json()["statut_verification"] == "declare"
    assert accepted.json()["degre_ordre"] == "pretre"

    pending = client_for(world.chancelier).get(f"{BASE}pending/").json()
    assert [p["email"] for p in pending["results"]] == ["emmanuel.tine@test.sn"]
    assert client_for(world.chancelier_thies).get(f"{BASE}pending/").json()["count"] == 0

    validated = client_for(world.chancelier).post(f"{BASE}{newcomer.pk}/validate/")
    assert validated.json()["statut_verification"] == "verifie"
    assert client_for(world.chancelier).get(f"{BASE}pending/").json()["count"] == 0
    actions = set(AuditEvent.objects.values_list("action", flat=True))
    assert {"compte.invitation", "compte.invitation_acceptation", "compte.validation"} <= actions
    # Le lien a servi : il n'est plus valable.
    again = client_for().post(f"{BASE}invitations/validate/", {"token": token}, format="json")
    assert again.status_code == 410


def test_refuse_needs_reason_then_deactivate_and_activate(world):
    token = token_of(invite(world))
    newcomer = BaseUserFactory(email="emmanuel.tine@test.sn")
    client_for(newcomer).post(f"{BASE}invitations/accept/", {"token": token}, format="json")
    manager = client_for(world.chancelier)
    assert manager.post(f"{BASE}{newcomer.pk}/refuse/", {"reason": ""}, format="json").status_code == 400
    refused = manager.post(f"{BASE}{newcomer.pk}/refuse/", {"reason": "Pièces à compléter"}, format="json")
    assert refused.json()["statut_verification"] == "rejete"
    assert refused.json()["verification_note"] == "Pièces à compléter"
    assert manager.post(f"{BASE}{newcomer.pk}/deactivate/").json()["is_active"] is False
    assert manager.post(f"{BASE}{newcomer.pk}/activate/").json()["is_active"] is True
    assert AuditEvent.objects.filter(action="compte.desactivation", node=world.saint_dominique).exists()
    # Hors de son diocèse : 404.
    assert client_for(world.chancelier_thies).post(f"{BASE}{newcomer.pk}/deactivate/").status_code == 404


def test_accept_with_another_email_is_refused(world):
    token = token_of(invite(world))
    intruder = BaseUserFactory(email="autre@test.sn")
    response = client_for(intruder).post(f"{BASE}invitations/accept/", {"token": token}, format="json")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invitation_email_mismatch"


def test_expired_revoked_and_rights(world):
    created = invite(world)
    token = token_of(created)
    ClergyInvitation.objects.update(expires_at=timezone.now() - datetime.timedelta(minutes=1))
    expired = client_for().post(f"{BASE}invitations/validate/", {"token": token}, format="json")
    assert expired.status_code == 410 and expired.json()["error"]["code"] == "invitation_expiree"
    listing = client_for(world.chancelier).get(f"{BASE}invitations/", {"status": "expiree"}).json()
    assert listing["count"] == 1 and listing["results"][0]["status"] == "expiree"

    ClergyInvitation.objects.update(expires_at=timezone.now() + datetime.timedelta(days=1))
    revoked = client_for(world.chancelier).post(f"{BASE}invitations/{created.json()['id']}/revoke/")
    assert revoked.json()["status"] == "revoquee"
    assert client_for().post(f"{BASE}invitations/validate/", {"token": token}, format="json").status_code == 410

    # Un curé n'invite pas ; Thiès n'invite pas sur Dakar ; la plateforme invite partout.
    assert invite(world, actor=world.cure).status_code == 403
    assert invite(world, actor=world.chancelier_thies).status_code == 403
    assert invite(world, actor=SuperAdminFactory(), email="autre@test.sn").status_code == 201
    laic = invite(world, email="x@test.sn", etat_de_vie="clerc", degre_ordre="aucun")
    assert laic.json()["error"]["code"] == "degre_ordre_required"
    dup = invite(world, email="autre@test.sn")
    assert dup.json()["error"]["code"] == "invitation_duplicate"
