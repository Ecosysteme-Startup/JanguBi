"""Paroisses multiples (décisions 6-8 du 29/09/2026) : une principale, des secondaires, adhésion
libre, retrait par la paroisse, fil d'annonces séparé, migration depuis ``paroisse_suivie``."""

import importlib

import pytest
from django.apps import apps as django_apps
from django.utils import timezone
from rest_framework.test import APIClient

from apps.hierarchy import services_memberships
from apps.hierarchy.models import AuditEvent, ParishMembership
from apps.hierarchy.tests.factories import nominate, person, priest
from apps.users.models import BaseUser

pytestmark = pytest.mark.django_db

ME = "/api/v1/me/paroisses/"


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _codes(response) -> list[tuple[str, bool]]:
    return [(row["paroisse"]["code"], row["principale"]) for row in response.json()]


def test_first_parish_is_primary_then_secondaries(tree):
    marie = person("mt.diouf@test.sn")
    client = _client(marie)

    assert client.get(ME).json() == []
    first = client.post(ME, {"paroisse_id": str(tree.saint_dominique.pk)}, format="json")
    second = client.post(ME, {"paroisse_id": str(tree.sainte_therese.pk)}, format="json")
    again = client.post(ME, {"paroisse_id": str(tree.sainte_therese.pk)}, format="json")  # idempotent

    assert first.status_code == 201
    assert _codes(second) == [("T-SD", True), ("T-ST", False)]
    assert _codes(again) == [("T-SD", True), ("T-ST", False)]
    marie.refresh_from_db()
    assert marie.paroisse_suivie == tree.saint_dominique  # copie de la principale
    assert client.get("/api/v1/me/paroisse-suivie/").json()["node"]["code"] == "T-SD"


def test_single_primary_and_switch(tree):
    marie = person("mt.diouf@test.sn")
    client = _client(marie)
    client.post(ME, {"paroisse_id": str(tree.saint_dominique.pk)}, format="json")
    client.post(ME, {"paroisse_id": str(tree.sainte_therese.pk)}, format="json")

    switched = client.put(f"{ME}{tree.sainte_therese.pk}/principale/")

    assert switched.status_code == 200
    assert _codes(switched) == [("T-ST", True), ("T-SD", False)]
    assert ParishMembership.objects.filter(user=marie, is_primary=True).count() == 1
    marie.refresh_from_db()
    assert marie.paroisse_suivie == tree.sainte_therese
    assert client.put(f"{ME}{tree.thies_parish.pk}/principale/").status_code == 404


def test_add_as_primary_directly(tree):
    marie = person("mt.diouf@test.sn")
    client = _client(marie)
    client.post(ME, {"paroisse_id": str(tree.saint_dominique.pk)}, format="json")

    response = client.post(ME, {"paroisse_id": str(tree.thies_parish.pk), "principale": True}, format="json")

    assert _codes(response) == [("T-THI-CATH", True), ("T-SD", False)]


def test_leaving_the_primary_promotes_the_oldest_secondary(tree):
    marie = person("mt.diouf@test.sn")
    client = _client(marie)
    for node in (tree.saint_dominique, tree.sainte_therese, tree.thies_parish):
        client.post(ME, {"paroisse_id": str(node.pk)}, format="json")

    assert client.delete(f"{ME}{tree.saint_dominique.pk}/").status_code == 204
    assert _codes(client.get(ME)) == [("T-ST", True), ("T-THI-CATH", False)]
    marie.refresh_from_db()
    assert marie.paroisse_suivie == tree.sainte_therese

    client.delete(f"{ME}{tree.sainte_therese.pk}/")
    client.delete(f"{ME}{tree.thies_parish.pk}/")
    marie.refresh_from_db()
    assert marie.paroisse_suivie is None
    assert client.delete(f"{ME}{tree.thies_parish.pk}/").status_code == 404


def test_only_a_parish_can_be_joined(tree):
    response = _client(person()).post(ME, {"paroisse_id": str(tree.dakar.pk)}, format="json")
    assert response.status_code == 400 and response.json()["error"]["code"] == "not_a_parish"


def test_legacy_follower_without_row_is_adopted(tree):
    """Un compte dont ``paroisse_suivie`` a été écrit directement garde cette paroisse en principale."""
    marie = person("mt.diouf@test.sn", paroisse_suivie=tree.saint_dominique)
    client = _client(marie)

    assert _codes(client.get(ME)) == [("T-SD", True)]
    assert _codes(client.post(ME, {"paroisse_id": str(tree.sainte_therese.pk)}, format="json")) == [
        ("T-SD", True),
        ("T-ST", False),
    ]


def test_legacy_put_replaces_the_primary_and_keeps_secondaries(tree):
    marie = person("mt.diouf@test.sn")
    client = _client(marie)
    client.post(ME, {"paroisse_id": str(tree.saint_dominique.pk)}, format="json")
    client.post(ME, {"paroisse_id": str(tree.sainte_therese.pk)}, format="json")

    client.put("/api/v1/me/paroisse-suivie/", {"node_id": str(tree.thies_parish.pk)}, format="json")

    assert _codes(client.get(ME)) == [("T-THI-CATH", True), ("T-ST", False)]


# --- Côté paroisse -------------------------------------------------------------------------------


@pytest.fixture
def parish_staff(tree):
    cure = priest("pere.tine@sd.sn")
    nominate(cure, "cure", tree.saint_dominique)
    secretaire = person("cecile.coly@sd.sn")
    nominate(secretaire, "secretaire_paroissial", tree.saint_dominique)
    return cure, secretaire


def test_parish_lists_and_removes_a_member_who_cannot_rejoin_alone(tree, parish_staff):
    cure, secretaire = parish_staff
    marie = person("mt.diouf@test.sn")
    services_memberships.membership_join(user=marie, node=tree.saint_dominique)
    services_memberships.membership_join(user=marie, node=tree.sainte_therese)
    base = f"/api/v1/hierarchy/nodes/{tree.saint_dominique.pk}/membres/"

    listed = _client(secretaire).get(base).json()
    assert [r["user_id"] for r in listed["results"]] == [str(marie.pk)]
    assert _client(marie).get(base).status_code == 403  # fidèle : pas de paroissiens.gerer

    assert _client(cure).delete(f"{base}{marie.pk}/").status_code == 204
    marie.refresh_from_db()
    assert marie.paroisse_suivie == tree.sainte_therese  # la secondaire devient principale
    assert AuditEvent.objects.filter(action="paroisse.membre_retire").count() == 1
    assert _client(cure).get(base).json()["results"] == []
    assert len(_client(cure).get(base, {"retires": "true"}).json()["results"]) == 1

    rejoin = _client(marie).post(ME, {"paroisse_id": str(tree.saint_dominique.pk)}, format="json")
    assert rejoin.status_code == 403 and rejoin.json()["error"]["code"] == "retire_par_la_paroisse"

    restored = _client(cure).post(f"{base}{marie.pk}/retablir/")
    assert restored.status_code == 200 and restored.json()["retire_le"] is None
    assert _codes(_client(marie).get(ME)) == [("T-ST", True), ("T-SD", False)]


def test_other_parish_staff_cannot_remove(tree, parish_staff):
    cure_st = priest("cure@st.sn")
    nominate(cure_st, "cure", tree.sainte_therese)
    marie = person("mt.diouf@test.sn")
    services_memberships.membership_join(user=marie, node=tree.saint_dominique)

    url = f"/api/v1/hierarchy/nodes/{tree.saint_dominique.pk}/membres/{marie.pk}/"
    assert _client(cure_st).delete(url).status_code == 403
    assert ParishMembership.objects.get(user=marie).removed_by_parish_at is None


def test_bishop_does_not_get_member_lists(tree):
    """Donnée personnelle : au-dessus de la paroisse, pas de liste nominative (RG-11)."""
    eveque = priest("eveque@dakar.sn")
    BaseUser.objects.filter(pk=eveque.pk).update(degre_ordre="eveque")
    eveque.refresh_from_db()
    nominate(eveque, "eveque_diocesain", tree.dakar)
    url = f"/api/v1/hierarchy/nodes/{tree.saint_dominique.pk}/membres/"
    assert _client(eveque).get(url).status_code == 403


def test_account_deletion_erases_memberships(tree):
    from apps.users import services_privacy

    marie = person("mt.diouf@test.sn")
    services_memberships.membership_join(user=marie, node=tree.saint_dominique)
    services_privacy.account_delete(user=marie)
    assert not ParishMembership.objects.filter(user=marie).exists()


# --- Fil des paroisses secondaires ---------------------------------------------------------------


def test_secondary_parishes_have_their_own_feed(tree):
    from apps.news.tests.factories import ArticleFactory

    marie = person("mt.diouf@test.sn")
    services_memberships.membership_join(user=marie, node=tree.saint_dominique)
    services_memberships.membership_join(user=marie, node=tree.sainte_therese)
    now = timezone.now()
    author = person("secretariat@sd.sn")
    kermesse = ArticleFactory(
        title="Kermesse",
        slug="kermesse",
        author=author,
        status="published",
        scope_node=tree.saint_dominique,
        published_at=now,
    )
    concert = ArticleFactory(
        title="Concert",
        slug="concert",
        author=author,
        status="published",
        scope_node=tree.sainte_therese,
        published_at=now,
    )
    ArticleFactory(title="Global", slug="global", author=author, status="published", scope_node=None, published_at=now)
    client = _client(marie)

    main = [a["id"] for a in client.get("/api/v1/me/feed/").json()["results"]]
    secondary = [a["id"] for a in client.get("/api/v1/me/feed/secondaires/").json()["results"]]

    assert str(kermesse.pk) in main and str(concert.pk) not in main
    assert secondary == [str(concert.pk)]
    filtered = client.get("/api/v1/me/feed/secondaires/", {"paroisse": str(tree.saint_dominique.pk)}).json()
    assert filtered["results"] == []  # la principale n'est pas une secondaire


# --- Migration de données ------------------------------------------------------------------------


def test_data_migration_turns_followed_parish_into_primary_membership(tree):
    migration = importlib.import_module("apps.hierarchy.migrations.0013_memberships_data")
    marie = person("mt.diouf@test.sn", paroisse_suivie=tree.saint_dominique)
    awa = person("awa@test.sn")

    migration.forward(django_apps, None)
    migration.forward(django_apps, None)  # idempotente

    row = ParishMembership.objects.get(user=marie)
    assert row.node == tree.saint_dominique and row.is_primary
    assert not ParishMembership.objects.filter(user=awa).exists()
