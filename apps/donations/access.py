"""Règles d'accès du module dons, au-dessus de ``peut()`` (cadrage DONS-00 §6).

La lecture fine (opérations, noms, export) ne vaut que pour une nomination **sur la paroisse
elle-même** : un droit hérité d'un diocèse ou d'un doyenné ne donne que des agrégats (RG-11).
"""

from typing import Any

from django.db.models import QuerySet

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.donations.enums import DIOCESE_TYPES, PARISH_TYPES
from apps.hierarchy import authz
from apps.hierarchy.models import Node


def is_parish(node: Node) -> bool:
    return node.type.code in PARISH_TYPES


def is_diocese(node: Node) -> bool:
    return node.type.code in DIOCESE_TYPES


def parish_level(user: Any, capability: str, node: Node) -> bool:
    """``capability`` détenue par une nomination posée sur cette paroisse même."""
    if not is_parish(node) or not authz.peut(user, capability, node):
        return False
    return any(g.capability == capability and g.node_id == str(node.pk) for g in authz.grants(user))


def require_parish_level(user: Any, capability: str, node: Node) -> None:
    if not is_parish(node):
        raise ApplicationError("Ce nœud n'est pas une paroisse.", code="not_a_parish")
    if not parish_level(user, capability, node):
        raise PermissionDeniedError("Vous n'avez pas ce droit sur cette paroisse.", code="dons_forbidden")
    authz.mfa_check(user)


def parishes_for(user: Any, capability: str) -> QuerySet[Node]:
    """Paroisses où ``user`` détient ``capability`` par une nomination locale."""
    ids = {g.node_id for g in authz.grants(user) if g.capability == capability and g.node_type in PARISH_TYPES}
    return Node.objects.filter(pk__in=ids).select_related("type")


def require_diocese(user: Any, capability: str, node: Node) -> None:
    if not is_diocese(node):
        raise ApplicationError("Ce nœud n'est pas un diocèse.", code="not_a_diocese")
    if not authz.peut(user, capability, node):
        raise PermissionDeniedError("Vous n'avez pas ce droit sur ce diocèse.", code="dons_forbidden")
    authz.mfa_check(user)


def office_code_for(user: Any, capability: str, node: Node) -> str:
    """Office qui donne ``capability`` sur ``node`` (trace « décidé par »)."""
    for g in authz.grants(user):
        if g.capability == capability and g.covers(node.path):
            return g.office
    return ""
