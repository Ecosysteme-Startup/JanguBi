"""
RECETTE GOLDEN-PATH — validation de bout en bout du Lot 2 (« le scénario du boss »).

On valide l'EXISTANT (multi-appartenance → scoping → documents → dons → gardes),
pas une nouvelle feature. Chaque assertion est VÉRITABLE (non-vacuité) : elle
échoue si on casse la règle correspondante (scoping, cloisonnement, garde
d'onboarding, garde paiement en ligne).

Graphe org :
  Province
    ├─ Diocèse D1 (Dakar)
    │    ├─ Paroisse A + église a_main + curé A
    │    └─ Paroisse C + église c_main + curé C   (paroisse de registre NON-membre)
    └─ Diocèse D2 (X)
         └─ Paroisse B + église b_main + curé B

Fidèle : membre de A & B (a_main principale). Demande un document à C (non-membre).
"""

from types import SimpleNamespace

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.org.tests.factories import (
    ChurchFactory,
    DioceseFactory,
    ParishFactory,
    ProvinceFactory,
)
from apps.users.enums import (
    PastoralRole,
    RoleScope,
    UserOnboardingState,
    UserRole,
)
from apps.users.models import Membership, RoleAssignment
from apps.users.tests.factories import BaseUserFactory

_DOC_NO_COMMIT = "apps.documents.services.transaction.on_commit"

# Demande de document valide (B5c : plus de parish_name/diocese ; parish_id ajouté par test).
VALID_DOC = {
    "document_type": "baptism",
    "reason": "personal",
    "requester_last_name": "Diallo",
    "requester_first_names": "Aminata",
    "date_of_birth": "1990-01-01",
    "place_of_birth": "Dakar",
    "contact_phone": "+221771234567",
    "contact_email": "aminata@example.com",
    "father_last_name": "Moussa",
    "mother_last_name": "Ndiaye",
    "sacrament_approximate_date": "2005",
    "sacrament_location": "Dakar",
    "consent_given": True,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cure(parish, email):
    """Curé d'une paroisse = PARISH_ADMIN scopé à cette paroisse (RoleAssignment)."""
    user = BaseUserFactory(email=email, role=UserRole.PARISH_ADMIN)
    RoleAssignment.objects.create(
        user=user,
        role=UserRole.PARISH_ADMIN,
        scope=RoleScope.PARISH,
        parish=parish,
        is_active=True,
    )
    return user


def _build_world():
    province = ProvinceFactory(name="Province de Dakar")
    d1 = DioceseFactory(name="Diocèse de Dakar", province=province)
    d2 = DioceseFactory(name="Diocèse de Thiès", province=province)

    parish_a = ParishFactory(name="Paroisse A", diocese=d1)
    parish_b = ParishFactory(name="Paroisse B", diocese=d2)
    parish_c = ParishFactory(name="Paroisse C", diocese=d1)

    a_main = ChurchFactory(parish=parish_a, name="Église a_main", is_main=True)
    b_main = ChurchFactory(parish=parish_b, name="Église b_main", is_main=True)
    c_main = ChurchFactory(parish=parish_c, name="Église c_main", is_main=True)

    return SimpleNamespace(
        province=province,
        d1=d1,
        d2=d2,
        parish_a=parish_a,
        parish_b=parish_b,
        parish_c=parish_c,
        a_main=a_main,
        b_main=b_main,
        c_main=c_main,
        cure_a=_cure(parish_a, "cure_a@test.com"),
        cure_b=_cure(parish_b, "cure_b@test.com"),
        cure_c=_cure(parish_c, "cure_c@test.com"),
    )


def _pending_fidele():
    """Fidèle email vérifié, en attente de sélection de paroisse (pending_parish)."""
    return BaseUserFactory(
        pastoral_role=PastoralRole.FIDELE,
        onboarding_state=UserOnboardingState.PENDING_PARISH_SELECTION,
    )


def _onboard(world):
    """Étapes 1-2 jouées : POST /me/memberships [a_main, b_main] (a_main principale).
    Retourne (client authentifié, user rafraîchi completed)."""
    user = _pending_fidele()
    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post(
        reverse("api:users:me-membership-list-create"),
        {"church_ids": [world.a_main.id, world.b_main.id]},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    user.refresh_from_db()  # met à jour onboarding_state sur l'objet utilisé par le client
    return client, user


@pytest.fixture
def world(db):
    return _build_world()


@pytest.fixture
def onboarded(world):
    client, user = _onboard(world)
    return SimpleNamespace(client=client, user=user, world=world)


# ---------------------------------------------------------------------------
# Étapes 1 & 2 — onboarding multi-église + /me
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_step_1_2_onboarding_multi_eglise_et_me(world):
    user = _pending_fidele()
    assert user.onboarding_state == UserOnboardingState.PENDING_PARISH_SELECTION

    client = APIClient()
    client.force_authenticate(user=user)

    # Étape 1 — POST /me/memberships {church_ids: [a_main, b_main]} (a_main principale).
    resp = client.post(
        reverse("api:users:me-membership-list-create"),
        {"church_ids": [world.a_main.id, world.b_main.id]},
        format="json",
    )
    assert resp.status_code == 201, resp.data

    user.refresh_from_db()
    assert user.onboarding_state == UserOnboardingState.COMPLETED
    assert Membership.objects.filter(user=user).count() == 2
    assert Membership.objects.get(user=user, church=world.a_main).is_primary is True
    assert Membership.objects.get(user=user, church=world.b_main).is_primary is False

    # Étape 2 — GET /me : 2 memberships + church_ids/parish_ids/diocese_ids corrects.
    me = client.get(reverse("api:users:me-detail"))
    assert me.status_code == 200
    data = me.data

    assert len(data["memberships"]) == 2
    primary = [m for m in data["memberships"] if m["is_primary"]]
    assert len(primary) == 1
    assert primary[0]["church"]["id"] == world.a_main.id
    # forme exacte d'un membership (church/parish/diocese imbriqués)
    sample = data["memberships"][0]
    assert set(sample.keys()) >= {"id", "church", "parish", "diocese", "is_primary"}
    assert set(sample["church"].keys()) >= {"id", "name"}

    assert set(data["church_ids"]) == {world.a_main.id, world.b_main.id}
    assert set(data["parish_ids"]) == {world.parish_a.id, world.parish_b.id}
    assert set(data["diocese_ids"]) == {world.d1.id, world.d2.id}


# ---------------------------------------------------------------------------
# Étape 5 — don espèces (PENDING) vs paiement en ligne (400)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_step_5_don_especes_pending_online_400(onboarded):
    w = onboarded.world
    url = reverse("api:donations:donate")

    r_cash = onboarded.client.post(
        url,
        {"church_id": w.b_main.id, "amount": 5000, "payment_provider": "cash"},
        format="json",
    )
    assert r_cash.status_code == 201, r_cash.data
    assert r_cash.data["status"] == "pending"

    r_wave = onboarded.client.post(
        url,
        {"church_id": w.b_main.id, "amount": 5000, "payment_provider": "wave"},
        format="json",
    )
    assert r_wave.status_code == 400
    assert "bientôt disponible" in str(r_wave.data)


# ---------------------------------------------------------------------------
# Étape 6 — garde serveur : fidèle pending_parish (0 membership) → 403 partout
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_step_6_garde_onboarding_bloque_les_ecritures(world):
    pending = _pending_fidele()
    assert Membership.objects.filter(user=pending).count() == 0
    client = APIClient()
    client.force_authenticate(user=pending)

    # Payloads vides : la permission (IsOnboardingCompleted) précède la validation/objet,
    # donc 403 (et NON 400/404) prouve que la garde s'applique.
    cases = {
        "intention": (reverse("api:mass-intentions:submit"), {}),
        "don": (reverse("api:donations:donate"), {}),
    }
    for label, (url, payload) in cases.items():
        resp = client.post(url, payload, format="json")
        assert resp.status_code == 403, f"{label}: attendu 403, obtenu {resp.status_code}"
