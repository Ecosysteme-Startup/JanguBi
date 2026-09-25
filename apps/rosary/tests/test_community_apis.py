import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.rosary.models import CommunityRosary
from apps.users.models import BaseUser

_STATE = {
    "fidele": ("laic", "aucun"),
    "diacre": ("clerc", "diacre_permanent"),
    "pretre": ("clerc", "pretre"),
}


def _make_user(email, pastoral_role="fidele"):
    user = BaseUser.objects.create_user(
        email=email,
        password="StrongPassw0rd!",
        phone_number=f"+221770{abs(hash(email)) % 1_000_000:06d}",
        is_active=True,
        is_verified=True,
    )
    user.etat_de_vie, user.degre_ordre = _STATE[pastoral_role]
    user.statut_verification = "verifie"
    user.save(update_fields=["etat_de_vie", "degre_ordre", "statut_verification"])
    return user


@pytest.fixture
def pretre_client(db):
    client = APIClient()
    user = _make_user("pretre@example.com", "pretre")
    client.force_authenticate(user=user)
    client._user = user
    return client


@pytest.fixture
def fidele_client(db):
    client = APIClient()
    user = _make_user("fidele@example.com", "fidele")
    client.force_authenticate(user=user)
    client._user = user
    return client


@pytest.mark.django_db
def test_community_rosary_start_clergy_201(pretre_client):
    url = reverse("api:rosary:community-list-create")
    resp = pretre_client.post(url, {"intention": "Pour la paix"}, format="json")
    assert resp.status_code == status.HTTP_201_CREATED
    assert CommunityRosary.objects.filter(initiator=pretre_client._user).count() == 1


@pytest.mark.django_db
def test_community_rosary_start_fidele_400(fidele_client):
    url = reverse("api:rosary:community-list-create")
    resp = fidele_client.post(url, {"intention": "Pour la paix"}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_community_rosary_list(pretre_client):
    CommunityRosary.objects.create(
        initiator=pretre_client._user,
        status=CommunityRosary.Status.ACTIVE,
    )
    url = reverse("api:rosary:community-list-create")
    resp = pretre_client.get(url)
    assert resp.status_code == status.HTTP_200_OK
    assert len(resp.data) == 1


@pytest.mark.django_db
def test_community_rosary_join(pretre_client, fidele_client):
    rosary = CommunityRosary.objects.create(
        initiator=pretre_client._user,
        status=CommunityRosary.Status.ACTIVE,
    )
    url = reverse("api:rosary:community-join", kwargs={"rosary_id": rosary.pk})
    resp = fidele_client.post(url)
    assert resp.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_community_rosary_submit_intention(pretre_client, fidele_client):
    rosary = CommunityRosary.objects.create(
        initiator=pretre_client._user,
        status=CommunityRosary.Status.ACTIVE,
    )
    url = reverse("api:rosary:community-intentions", kwargs={"rosary_id": rosary.pk})
    resp = fidele_client.post(url, {"text": "Pour les malades"}, format="json")
    assert resp.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
def test_community_rosary_end(pretre_client):
    rosary = CommunityRosary.objects.create(
        initiator=pretre_client._user,
        status=CommunityRosary.Status.ACTIVE,
    )
    url = reverse("api:rosary:community-end", kwargs={"rosary_id": rosary.pk})
    resp = pretre_client.post(url)
    assert resp.status_code == status.HTTP_200_OK
    rosary.refresh_from_db()
    assert rosary.status == CommunityRosary.Status.COMPLETED


@pytest.mark.django_db
def test_community_rosary_requires_auth():
    client = APIClient()
    url = reverse("api:rosary:community-list-create")
    resp = client.get(url)
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
