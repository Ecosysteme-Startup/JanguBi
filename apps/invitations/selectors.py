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
        "node", "invited_by__profile", "accepted_by", "justificatif"
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


ROLE_CHOICES = ("diacre_transitoire", "diacre_permanent", "pretre", "eveque", "consacre")


def accounts_list(*, user: Any, filters: dict[str, Any] | None = None) -> QuerySet[Any]:
    """Comptes invités (invitation acceptée) des nœuds où ``user`` a ``comptes.valider``.

    Filtres : ``node`` (nœud exact de l'invitation), ``diocese`` (sous-arbre d'un nœud), ``role``
    (degré d'ordre, ou ``consacre``), ``statut`` (statut de vérification, ou ``en_attente`` pour
    déclaré + complément demandé), ``q`` (nom ou e-mail).
    """
    from django.db.models import Q

    from apps.hierarchy.models import Node
    from apps.users.models import BaseUser

    filters = filters or {}
    invitations = ClergyInvitation.objects.filter(
        accepted_by=OuterRef("pk"), status=InvitationStatus.ACCEPTEE, node__in=_allowed_nodes(user)
    )
    if node_id := filters.get("node"):
        invitations = invitations.filter(node_id=node_id)
    if diocese_id := filters.get("diocese"):
        root = Node.objects.filter(pk=diocese_id).values_list("path", flat=True).first()
        invitations = invitations.filter(node__path__startswith=root) if root else invitations.none()
    qs = BaseUser.objects.filter(Exists(invitations)).exclude(pk=user.pk).select_related("profile")
    statut = filters.get("statut")
    if statut == "en_attente":
        qs = qs.filter(statut_verification__in=PENDING_STATUSES)
    elif statut:
        qs = qs.filter(statut_verification=statut)
    role = filters.get("role")
    if role == "consacre":
        qs = qs.filter(etat_de_vie="consacre")
    elif role:
        qs = qs.filter(degre_ordre=role)
    if q := (filters.get("q") or "").strip():
        qs = qs.filter(Q(email__icontains=q) | Q(profile__first_name__icontains=q) | Q(profile__last_name__icontains=q))
    return qs.order_by("declared_at", "email")


def pending_accounts(*, user: Any, node_id: Any = None, filters: dict[str, Any] | None = None) -> QuerySet[Any]:
    """Comptes invités, acceptés, en attente de validation (déclarés ou complément demandé)."""
    filters = {**(filters or {}), "statut": "en_attente"}
    if node_id:
        filters["node"] = node_id
    return accounts_list(user=user, filters=filters)


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
