"""Portée de l'administration des comptes (docs/ADMIN-KEYCLOAK.md §3).

Règle : administrateur plateforme > chancellerie / diocèse > paroisse.

- L'administrateur plateforme gère tous les comptes (sauf garde-fous : soi-même, dernier admin).
- Un titulaire de ``comptes.gerer`` gère un compte si et seulement si :
  1. le compte n'est ni le sien ni celui d'un administrateur plateforme ;
  2. le compte a au moins un nœud de rattachement (nœud gestionnaire, nominations en cours,
     invitation du clergé acceptée) et **tous** ces nœuds sont dans son périmètre ;
  3. il pourrait nommer à **chacun** des offices en cours du compte (jamais au-dessus de lui :
     un chancelier ne gère pas le compte de l'évêque, un curé celui d'un vicaire).
- Un fidèle inscrit seul, sans rattachement, relève de la plateforme.
"""

from typing import Any

from django.db.models import Q, QuerySet

from apps.core.exceptions import PermissionDeniedError
from apps.hierarchy import authz
from apps.hierarchy.models import Node, OfficeAssignment

CAPABILITY = "comptes.gerer"
OPEN_STATUSES = ("proposee", "active")


def is_platform(actor: Any) -> bool:
    return authz.is_platform_admin(actor)


def managed_nodes(actor: Any) -> QuerySet[Node]:
    return authz.noeuds_autorises(actor, CAPABILITY)


def can_administer(actor: Any) -> bool:
    return is_platform(actor) or authz.a_la_capacite(actor, CAPABILITY)


def _open_assignments(user: Any) -> QuerySet[OfficeAssignment]:
    return OfficeAssignment.objects.filter(person=user, status__in=OPEN_STATUSES).select_related(
        "node", "office_type"
    )


def account_scope_nodes(user: Any) -> list[Node]:
    """Nœuds de rattachement du compte (dédoublonnés)."""
    from apps.invitations.models import ClergyInvitation, InvitationStatus

    nodes: dict[Any, Node] = {}
    if user.admin_node_id:
        nodes[user.admin_node_id] = user.admin_node
    for assignment in _open_assignments(user):
        nodes[assignment.node_id] = assignment.node
    invitation = (
        ClergyInvitation.objects.filter(accepted_by=user, status=InvitationStatus.ACCEPTEE)
        .select_related("node")
        .order_by("-accepted_at")
        .first()
    )
    if invitation is not None:
        nodes[invitation.node_id] = invitation.node
    return list(nodes.values())


def primary_node(user: Any) -> Node | None:
    nodes = account_scope_nodes(user)
    return min(nodes, key=lambda n: len(n.path)) if nodes else None


def _can_appoint(actor: Any, assignment: OfficeAssignment) -> bool:
    from apps.hierarchy.services_offices import appointing_authority_check

    try:
        appointing_authority_check(actor=actor, office_type=assignment.office_type, node=assignment.node)
    except PermissionDeniedError:
        return False
    return True


def manage_denial(actor: Any, target: Any) -> str | None:
    """Motif du refus (code), ou ``None`` si ``actor`` peut gérer ``target``."""
    if is_platform(actor):
        return None
    if target.pk == getattr(actor, "pk", None):
        return "self_action"
    if target.keycloak_platform_admin:
        return "account_above_scope"
    if not authz.a_la_capacite(actor, CAPABILITY):
        return "comptes_forbidden"
    nodes = account_scope_nodes(target)
    if not nodes:
        return "account_platform_scope"
    allowed = set(managed_nodes(actor).filter(pk__in=[n.pk for n in nodes]).values_list("pk", flat=True))
    if any(n.pk not in allowed for n in nodes):
        return "account_out_of_scope"
    if any(not _can_appoint(actor, a) for a in _open_assignments(target)):
        return "account_above_scope"
    return None


_MESSAGES = {
    "self_action": "Votre propre compte se gère dans votre espace personnel.",
    "account_above_scope": "Ce compte relève d'une autorité supérieure à la vôtre.",
    "comptes_forbidden": "Vous ne gérez pas de comptes.",
    "account_platform_scope": "Ce compte relève de l'administration de la plateforme.",
    "account_out_of_scope": "Ce compte est hors de votre périmètre.",
}


def can_manage(actor: Any, target: Any) -> bool:
    return manage_denial(actor, target) is None


def require_manage(actor: Any, target: Any) -> None:
    code = manage_denial(actor, target)
    if code is not None:
        raise PermissionDeniedError(_MESSAGES[code], code=code)


def require_node(actor: Any, node: Node) -> None:
    """Création d'un compte : le nœud gestionnaire doit être dans le périmètre."""
    if is_platform(actor):
        return
    if not authz.peut(actor, CAPABILITY, node):
        raise PermissionDeniedError("Ce nœud est hors de votre périmètre.", code="node_out_of_scope")


def require_platform(actor: Any) -> None:
    if not is_platform(actor):
        raise PermissionDeniedError("Action réservée à l'administration de la plateforme.", code="platform_only")


def scope_q(actor: Any) -> Q:
    """Filtre SQL large des comptes visibles (la gestion fine passe par ``require_manage``)."""
    if is_platform(actor):
        return Q()
    nodes = managed_nodes(actor)
    from apps.invitations.models import ClergyInvitation, InvitationStatus

    return (
        Q(admin_node__in=nodes)
        | Q(pk__in=OfficeAssignment.objects.filter(node__in=nodes, status__in=OPEN_STATUSES).values("person_id"))
        | Q(
            pk__in=ClergyInvitation.objects.filter(node__in=nodes, status=InvitationStatus.ACCEPTEE).values(
                "accepted_by_id"
            )
        )
    ) & Q(keycloak_platform_admin=False) & ~Q(pk=getattr(actor, "pk", None))
