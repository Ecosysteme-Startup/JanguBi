from typing import Any

from django.db import transaction

from apps.core.exceptions import ApplicationError
from apps.hierarchy.persons import is_clerc_or_consecrated
from apps.rosary.community_events import (
    broadcast_frame_sync,
    decade_advanced_frame,
    intention_submitted_frame,
    rosary_ended_frame,
)


def _broadcast_on_commit(*, rosary_id: int, frame: dict[str, Any]) -> None:
    """Diffuse la trame APRÈS commit.

    Diffuser dans la transaction exposerait les clients à un événement dont
    l'écriture peut encore être annulée (participant voyant une décade qui
    n'existe pas en base). Même règle que les emails du projet.
    """
    transaction.on_commit(lambda: broadcast_frame_sync(rosary_id=rosary_id, frame=frame))


@transaction.atomic
def community_rosary_start(*, initiator, mystery_group_id: int | None = None, intention: str = ""):
    from apps.rosary.models import CommunityRosary

    if not is_clerc_or_consecrated(initiator):
        raise ApplicationError("Seul le clergé peut initier un chapelet communautaire.")

    return CommunityRosary.objects.create(
        initiator=initiator,
        mystery_group_id=mystery_group_id,
        intention=intention,
        status=CommunityRosary.Status.ACTIVE,
    )


@transaction.atomic
def community_rosary_join(*, rosary, user):
    from apps.rosary.models import RosaryParticipant

    if rosary.status != "active":
        raise ApplicationError("Ce chapelet n'est plus actif.")
    participant, _ = RosaryParticipant.objects.get_or_create(rosary=rosary, user=user)
    return participant


@transaction.atomic
def community_rosary_submit_intention(*, rosary, user, text: str):
    from apps.rosary.models import RosaryIntention

    if rosary.status != "active":
        raise ApplicationError("Ce chapelet n'est plus actif.")
    if not text.strip():
        raise ApplicationError("L'intention ne peut pas être vide.")
    intention = RosaryIntention.objects.create(rosary=rosary, submitted_by=user, text=text)
    _broadcast_on_commit(
        rosary_id=rosary.pk,
        frame=intention_submitted_frame(text=intention.text, submitted_by=user.email),
    )
    return intention


@transaction.atomic
def community_rosary_advance_decade(*, rosary, user):
    """Passe à la décade suivante (initiateur uniquement).

    Appelée par le consumer WebSocket, qui ne touche plus l'ORM.

    Volontairement **sans endpoint REST**, contrairement à ``end`` et
    ``submit_intention``. Ces deux-là ont un repli HTTP parce qu'ils répondent à
    un besoin de durabilité : clore une session dont le socket est mort, déposer
    une intention hors direct. Avancer la décade n'a pas d'équivalent — si le
    socket de l'initiateur est tombé, plus personne ne mène le chapelet et
    l'action utile est ``end``, déjà exposée. Un POST « décade suivante » sans
    numéro de décade attendu serait par ailleurs non idempotent : un double
    envoi ou un rejeu sauterait une dizaine sans que le client puisse le voir.
    """
    if rosary.initiator_id != user.pk:
        raise ApplicationError("Seul l'initiateur peut faire avancer le chapelet.")
    if rosary.status != "active":
        raise ApplicationError("Ce chapelet n'est plus actif.")
    rosary.current_decade += 1
    rosary.save(update_fields=["current_decade", "updated_at"])
    _broadcast_on_commit(
        rosary_id=rosary.pk,
        frame=decade_advanced_frame(current_decade=rosary.current_decade),
    )
    return rosary


@transaction.atomic
def community_rosary_end(*, rosary, user):
    from django.utils import timezone

    if rosary.initiator_id != user.pk:
        raise ApplicationError("Seul l'initiateur peut terminer le chapelet.")
    if rosary.status != "active":
        raise ApplicationError("Ce chapelet n'est plus actif.")
    rosary.status = "completed"
    rosary.ended_at = timezone.now()
    rosary.save(update_fields=["status", "ended_at", "updated_at"])
    # Sans cette diffusion, une clôture REST (socket de l'initiateur coupé)
    # laissait les autres participants devant une session morte.
    _broadcast_on_commit(rosary_id=rosary.pk, frame=rosary_ended_frame())
    return rosary


def community_rosary_list_active():
    from apps.rosary.models import CommunityRosary

    return CommunityRosary.objects.filter(status="active").select_related("initiator", "mystery_group").order_by("-started_at")


def community_rosary_get(*, rosary_id: int):
    from apps.rosary.models import CommunityRosary

    try:
        return CommunityRosary.objects.select_related("initiator", "mystery_group").get(pk=rosary_id)
    except CommunityRosary.DoesNotExist:
        raise ApplicationError("Session de chapelet introuvable.")
