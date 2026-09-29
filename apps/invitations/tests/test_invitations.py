"""Invitations et validation des comptes du clergé (lot V1-routes)."""

import datetime
import uuid
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


def _file(owner, *, finished=True):
    from apps.files.models import File

    return File.objects.create(
        original_file_name="celebret.pdf",
        file_name=f"f-{uuid.uuid4()}.pdf",
        file_type="application/pdf",
        uploaded_by=owner,
        upload_finished_at=timezone.now() if finished else None,
        file="files/celebret.pdf",
    )


def test_optional_justificatif_on_invite_and_accept(world):
    other = _file(world.cure)
    assert invite(world, justificatif_id=other.pk).json()["error"]["code"] == "file_forbidden"
    mine = _file(world.chancelier)
    created = invite(world, justificatif_id=mine.pk)
    assert created.status_code == 201, created.content
    assert created.json()["justificatif"]["id"] == mine.pk
    assert created.json()["justificatif"]["file_name"] == "celebret.pdf"

    token = token_of(invite(world, email="diacre@test.sn", degre_ordre="diacre_permanent"))
    newcomer = BaseUserFactory(email="diacre@test.sn")
    incomplete = _file(newcomer, finished=False)
    bad = client_for(newcomer).post(
        f"{BASE}invitations/accept/", {"token": token, "justificatif_id": incomplete.pk}, format="json"
    )
    assert bad.json()["error"]["code"] == "file_incomplete"
    proof = _file(newcomer)
    ok = client_for(newcomer).post(
        f"{BASE}invitations/accept/", {"token": token, "justificatif_id": proof.pk}, format="json"
    )
    assert ok.status_code == 200 and ok.json()["justificatif"]["id"] == proof.pk
    # Sans pièce : reste facultatif.
    token2 = token_of(invite(world, email="sans@test.sn"))
    plain = client_for(BaseUserFactory(email="sans@test.sn")).post(
        f"{BASE}invitations/accept/", {"token": token2}, format="json"
    )
    assert plain.status_code == 200 and plain.json()["justificatif"] is None


def test_account_filters_and_validated_list(world):
    people = {}
    for email, degre, node in (
        ("pretre@test.sn", "pretre", world.saint_dominique),
        ("diacre@test.sn", "diacre_permanent", world.saint_dominique),
        ("thies@test.sn", "pretre", world.thies),
    ):
        actor = SuperAdminFactory() if node == world.thies else world.chancelier
        token = token_of(invite(world, actor=actor, email=email, degre_ordre=degre, node=str(node.pk)))
        people[email] = BaseUserFactory(email=email)
        client_for(people[email]).post(f"{BASE}invitations/accept/", {"token": token}, format="json")
    manager = client_for(world.chancelier)
    manager.post(f"{BASE}{people['pretre@test.sn'].pk}/validate/")

    validated = manager.get(f"{BASE}validated/").json()
    assert [a["email"] for a in validated["results"]] == ["pretre@test.sn"]
    assert manager.get(f"{BASE}", {"role": "diacre_permanent"}).json()["results"][0]["email"] == "diacre@test.sn"
    assert manager.get(f"{BASE}", {"statut": "en_attente"}).json()["count"] == 1
    assert manager.get(f"{BASE}", {"statut": "verifie"}).json()["count"] == 1
    assert manager.get(f"{BASE}pending/", {"role": "pretre"}).json()["count"] == 0
    assert manager.get(f"{BASE}", {"diocese": str(world.dakar.pk)}).json()["count"] == 2
    # Thiès est hors du périmètre du chancelier de Dakar ; la plateforme voit tout.
    assert manager.get(f"{BASE}", {"diocese": str(world.thies.pk)}).json()["count"] == 0
    platform = client_for(SuperAdminFactory())
    assert platform.get(f"{BASE}", {"diocese": str(world.thies.pk)}).json()["count"] == 1
    assert manager.get(f"{BASE}", {"role": "inconnu"}).status_code == 400


def _pending_newcomer(world, email="emmanuel.tine@test.sn", actor=None):
    token = token_of(invite(world, actor=actor, email=email))
    newcomer = BaseUserFactory(email=email)
    assert client_for(newcomer).post(f"{BASE}invitations/accept/", {"token": token}, format="json").status_code == 200
    return newcomer


def test_both_chancellery_and_platform_can_validate(world):
    """Décision : la chancellerie diocésaine (comptes.valider sur le diocèse) ET l'équipe plateforme
    valident les comptes du clergé, quel que soit l'auteur de l'invitation."""
    platform_admin = SuperAdminFactory()
    platform = client_for(platform_admin)
    by_chancery = _pending_newcomer(world, "a@test.sn")
    by_platform = _pending_newcomer(world, "b@test.sn", actor=platform_admin)
    refused_by_platform = _pending_newcomer(world, "c@test.sn")

    # Les deux voient les comptes en attente du diocèse de Dakar.
    assert client_for(world.chancelier).get(f"{BASE}pending/").json()["count"] == 3
    assert platform.get(f"{BASE}pending/").json()["count"] == 3

    # Invité par la plateforme, validé par la chancellerie ; et inversement.
    assert (
        client_for(world.chancelier).post(f"{BASE}{by_platform.pk}/validate/").json()["statut_verification"]
        == "verifie"
    )
    ok = platform.post(f"{BASE}{by_chancery.pk}/validate/")
    assert ok.status_code == 200 and ok.json()["statut_verification"] == "verifie"
    refused = platform.post(f"{BASE}{refused_by_platform.pk}/refuse/", {"reason": "Pièce illisible"}, format="json")
    assert refused.json()["statut_verification"] == "rejete"
    assert platform.post(f"{BASE}{by_chancery.pk}/deactivate/").json()["is_active"] is False
    by_chancery.refresh_from_db()
    assert by_chancery.verified_by_id == platform_admin.pk
    assert AuditEvent.objects.filter(action="compte.validation", actor=platform_admin).exists()
    assert AuditEvent.objects.filter(action="compte.validation", actor=world.chancelier).exists()


def test_validation_refused_outside_diocese_and_without_capability(world):
    newcomer = _pending_newcomer(world)
    # Chancellerie d'un autre diocèse : 404 (compte hors périmètre).
    assert client_for(world.chancelier_thies).post(f"{BASE}{newcomer.pk}/validate/").status_code == 404
    # Curé sans comptes.valider, simple fidèle : 403.
    assert client_for(world.cure).post(f"{BASE}{newcomer.pk}/validate/").status_code == 403
    assert client_for(BaseUserFactory()).post(f"{BASE}{newcomer.pk}/validate/").status_code == 403
    newcomer.refresh_from_db()
    assert newcomer.statut_verification == "declare"
