"""Lectures du chapelet communautaire (HackSoft : aucune écriture ici)."""

from django.db.models import QuerySet

from apps.rosary.models import CommunityRosary, RosaryIntention, RosaryParticipant
from apps.users.models import BaseUser


def community_rosary_intentions_list(*, rosary_id: int) -> QuerySet[RosaryIntention]:
    """Intentions d'une session, dans l'ordre de dépôt (``Meta.ordering``)."""
    return RosaryIntention.objects.filter(rosary_id=rosary_id).select_related("submitted_by")


def community_rosary_participants_list(*, rosary_id: int) -> QuerySet[RosaryParticipant]:
    return RosaryParticipant.objects.filter(rosary_id=rosary_id).select_related("user").order_by("joined_at")


def community_rosary_participant_count(*, rosary_id: int) -> int:
    return RosaryParticipant.objects.filter(rosary_id=rosary_id).count()


def community_rosary_is_participant(*, rosary_id: int, user: BaseUser) -> bool:
    return RosaryParticipant.objects.filter(rosary_id=rosary_id, user=user).exists()


def community_rosary_can_read_intentions(*, rosary: CommunityRosary, user: BaseUser) -> bool:
    """Qui peut lire les intentions d'une session.

    Aligné sur le RBAC déjà en vigueur côté temps réel : ``intention_submitted``
    est diffusé au **groupe de la session**, donc à ses participants. La lecture
    différée applique la même frontière — ni plus (une intention de prière n'est
    pas publique à tout compte authentifié), ni moins (un participant doit
    retrouver ce qui a été déposé avant son arrivée).

    L'initiateur est autorisé même sans ligne ``RosaryParticipant`` : il ouvre la
    session via REST et n'est enregistré participant qu'à la connexion socket.
    """
    if rosary.initiator_id == user.pk:
        return True
    return community_rosary_is_participant(rosary_id=rosary.pk, user=user)
