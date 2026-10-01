"""Diffusion temps réel du chapelet communautaire.

Ces tests portent sur ce que les endpoints REST **diffusent**, pas seulement sur
ce qu'ils persistent : une clôture REST doit atteindre les participants dont
l'initiateur n'est plus le socket porteur.
"""

from itertools import count

import pytest
from django.db import transaction
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.core.exceptions import ApplicationError
from apps.rosary.community_events import rosary_group_name
from apps.rosary.community_services import (
    community_rosary_advance_decade,
    community_rosary_end,
    community_rosary_submit_intention,
)
from apps.rosary.models import CommunityRosary, RosaryIntention, RosaryParticipant
from apps.users.models import BaseUser

_phone_seq = count(100_000)


_STATE = {
    "fidele": ("laic", "aucun"),
    "diacre": ("clerc", "diacre_permanent"),
    "pretre": ("clerc", "pretre"),
}


def _make_user(email, etat="fidele"):
    user = BaseUser.objects.create_user(
        email=email,
        password="StrongPassw0rd!",
        phone_number=f"+221770{next(_phone_seq):06d}",
        is_active=True,
        is_verified=True,
    )
    user.etat_de_vie, user.degre_ordre = _STATE[etat]
    user.statut_verification = "verifie"
    user.save(update_fields=["etat_de_vie", "degre_ordre", "statut_verification"])
    return user


class _RecordingChannelLayer:
    """Channel layer factice : enregistre (groupe, enveloppe) sans Redis."""

    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    async def group_send(self, group, message):
        self.sent.append((group, message))

    def frames(self) -> list[dict]:
        return [message["frame"] for _group, message in self.sent]


@pytest.fixture
def layer(monkeypatch):
    spy = _RecordingChannelLayer()
    monkeypatch.setattr("apps.rosary.community_events.get_channel_layer", lambda: spy)
    return spy


@pytest.fixture
def pretre(db):
    return _make_user("pretre.rt@example.com", "pretre")


@pytest.fixture
def fidele(db):
    return _make_user("fidele.rt@example.com", "fidele")


@pytest.fixture
def rosary(pretre):
    return CommunityRosary.objects.create(initiator=pretre, status=CommunityRosary.Status.ACTIVE)


# ── Diffusion depuis les services ──────────────────────────────────────────


@pytest.mark.django_db
def test_submit_intention_broadcasts_frame(layer, rosary, fidele, django_capture_on_commit_callbacks):
    # Act
    with django_capture_on_commit_callbacks(execute=True):
        community_rosary_submit_intention(rosary=rosary, user=fidele, text="Pour les malades")

    # Assert
    group, envelope = layer.sent[0]
    assert group == rosary_group_name(rosary.pk)
    assert envelope["frame"] == {
        "type": "intention_submitted",
        "text": "Pour les malades",
        "submitted_by": fidele.email,
    }


@pytest.mark.django_db
def test_end_broadcasts_rosary_ended(layer, rosary, pretre, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        community_rosary_end(rosary=rosary, user=pretre)

    group, envelope = layer.sent[0]
    assert group == rosary_group_name(rosary.pk)
    assert envelope["frame"] == {"type": "rosary_ended"}


@pytest.mark.django_db
def test_advance_broadcasts_decade_advanced(layer, rosary, pretre, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        community_rosary_advance_decade(rosary=rosary, user=pretre)

    rosary.refresh_from_db()
    assert rosary.current_decade == 1
    assert layer.frames() == [{"type": "decade_advanced", "current_decade": 1}]


@pytest.mark.django_db
def test_advance_refused_for_non_initiator_and_silent(layer, rosary, fidele):
    with pytest.raises(ApplicationError):
        community_rosary_advance_decade(rosary=rosary, user=fidele)

    assert layer.sent == []


@pytest.mark.django_db
def test_end_refused_on_already_completed_session(layer, rosary, pretre):
    rosary.status = CommunityRosary.Status.COMPLETED
    rosary.save(update_fields=["status"])

    with pytest.raises(ApplicationError):
        community_rosary_end(rosary=rosary, user=pretre)

    assert layer.sent == []


@pytest.mark.django_db
def test_no_broadcast_when_transaction_rolls_back(layer, rosary, fidele):
    """Rien ne part avant commit : pas d'événement pour une écriture annulée."""

    class _Rollback(Exception):
        pass

    with pytest.raises(_Rollback):
        with transaction.atomic():
            community_rosary_submit_intention(rosary=rosary, user=fidele, text="Annulée")
            raise _Rollback

    assert layer.sent == []
    assert RosaryIntention.objects.count() == 0


# ── Diffusion depuis les endpoints REST (le manque corrigé) ────────────────


@pytest.mark.django_db
def test_rest_end_broadcasts_to_participants(layer, rosary, pretre, django_capture_on_commit_callbacks):
    """Clôture REST (socket de l'initiateur coupé) → les autres sont prévenus."""
    client = APIClient()
    client.force_authenticate(user=pretre)
    url = reverse("api:rosary:community-end", kwargs={"rosary_id": rosary.pk})

    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(url)

    assert resp.status_code == status.HTTP_200_OK
    assert layer.frames() == [{"type": "rosary_ended"}]


@pytest.mark.django_db
def test_rest_intention_broadcasts_to_participants(layer, rosary, fidele, django_capture_on_commit_callbacks):
    client = APIClient()
    client.force_authenticate(user=fidele)
    url = reverse("api:rosary:community-intentions", kwargs={"rosary_id": rosary.pk})

    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(url, {"text": "Pour la paix"}, format="json")

    assert resp.status_code == status.HTTP_201_CREATED
    assert layer.frames() == [{"type": "intention_submitted", "text": "Pour la paix", "submitted_by": fidele.email}]


# ── GET intentions ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_list_intentions_returns_history_for_participant(rosary, pretre, fidele):
    RosaryIntention.objects.create(rosary=rosary, submitted_by=pretre, text="Première")
    RosaryIntention.objects.create(rosary=rosary, submitted_by=fidele, text="Seconde")
    RosaryParticipant.objects.create(rosary=rosary, user=fidele)

    client = APIClient()
    client.force_authenticate(user=fidele)
    url = reverse("api:rosary:community-intentions", kwargs={"rosary_id": rosary.pk})
    resp = client.get(url)

    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["count"] == 2
    assert [row["text"] for row in resp.data["results"]] == ["Première", "Seconde"]
    assert resp.data["results"][0]["submitted_by"] == pretre.email


@pytest.mark.django_db
def test_list_intentions_allowed_for_initiator_without_participant_row(rosary, pretre):
    RosaryIntention.objects.create(rosary=rosary, submitted_by=pretre, text="Intention")

    client = APIClient()
    client.force_authenticate(user=pretre)
    url = reverse("api:rosary:community-intentions", kwargs={"rosary_id": rosary.pk})
    resp = client.get(url)

    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["count"] == 1


@pytest.mark.django_db
def test_list_intentions_forbidden_for_non_participant(rosary, pretre, fidele):
    RosaryIntention.objects.create(rosary=rosary, submitted_by=pretre, text="Privée")

    client = APIClient()
    client.force_authenticate(user=fidele)  # n'a jamais rejoint
    url = reverse("api:rosary:community-intentions", kwargs={"rosary_id": rosary.pk})
    resp = client.get(url)

    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_list_intentions_unknown_session_400(pretre):
    client = APIClient()
    client.force_authenticate(user=pretre)
    url = reverse("api:rosary:community-intentions", kwargs={"rosary_id": 999_999})
    assert client.get(url).status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_list_intentions_requires_auth(rosary):
    url = reverse("api:rosary:community-intentions", kwargs={"rosary_id": rosary.pk})
    assert APIClient().get(url).status_code == status.HTTP_401_UNAUTHORIZED
