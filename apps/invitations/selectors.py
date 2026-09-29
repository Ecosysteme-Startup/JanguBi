"""Lectures : invitations et comptes du clergé en attente (lot V1-routes)."""

from typing import Any

from django.db.models import Exists, OuterRef, QuerySet
from django.utils import timezone

from apps.core.exceptions import NotFoundError
from apps.hierarchy import authz
from apps.invitations.models import ClergyInvitation, InvitationStatus
from apps.invitations.services import PENDING_STATUSES


def _allowed_nodes(user: Any) -> QuerySet[Any]:
    return authz.noeuds_autorises(user, "comptes.valider")


def invitation_list(*, user: Any, filters: dict[str, Any] | None = None) -> QuerySet[ClergyInvitation]:
    """Invitations des nœuds où ``user`` a ``comptes.valider``. ``status=expiree`` : en attente
    dont la date est dépassée ; ``status=en_attente`` : seulement les encore valables."""
    filters = filters or {}
    qs = ClergyInvitation.objects.filter(node__in=_allowed_nodes(user)).select_related(
        "node", "invited_by__profile", "accepted_by"
    )
    now = timezone.now()
    status = filters.get("status")
    if status == InvitationStatus.EXPIREE:
        qs = qs.filter(status=InvitationStatus.EN_ATTENTE, expires_at__lte=now)
    elif status == InvitationStatus.EN_ATTENTE:
        qs = qs.filter(status=status, expires_at__gt=now)
    elif status:
        qs = qs.filter(status=status)
    if node_id := filters.get("node"):
        qs = qs.filter(node_id=node_id)
    if q := (filters.get("q") or "").strip():
        qs = qs.filter(email__icontains=q)
    return qs.order_by("-created_at")


def invitation_get(*, user: Any, invitation_id: Any) -> ClergyInvitation:
    obj = invitation_list(user=user).filter(pk=invitation_id).first()
    if obj is None:
        raise NotFoundError("Invitation introuvable.")
    return obj


def pending_accounts(*, user: Any, node_id: Any = None) -> QuerySet[Any]:
    """Comptes invités, acceptés, en attente de validation (déclarés ou complément demandé)."""
    from apps.users.models import BaseUser

    invitations = ClergyInvitation.objects.filter(
        accepted_by=OuterRef("pk"), status=InvitationStatus.ACCEPTEE, node__in=_allowed_nodes(user)
    )
    if node_id:
        invitations = invitations.filter(node_id=node_id)
    return (
        BaseUser.objects.filter(statut_verification__in=PENDING_STATUSES)
        .filter(Exists(invitations))
        .exclude(pk=user.pk)
        .select_related("profile")
        .order_by("declared_at", "email")
    )


def account_get(*, user: Any, person_id: Any, scoped: bool = True) -> Any:
    """Compte invité dans le périmètre de ``user`` (404 sinon, sans révéler son existence).
    ``scoped=False`` : la personne elle-même, juste après son acceptation."""
    from apps.users.models import BaseUser

    invitations = ClergyInvitation.objects.filter(accepted_by=OuterRef("pk"), status=InvitationStatus.ACCEPTEE)
    if scoped:
        invitations = invitations.filter(node__in=_allowed_nodes(user))
    person = BaseUser.objects.filter(pk=person_id).filter(Exists(invitations)).select_related("profile").first()
    if person is None:
        raise NotFoundError("Compte introuvable.")
    return person
