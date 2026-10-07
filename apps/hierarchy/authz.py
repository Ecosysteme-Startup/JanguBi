"""Moteur d'autorisation : offices et capacités sur l'arbre des juridictions (ADR-003).

    peut(user, capacite, noeud) =
      il existe une nomination ACTIVE de l'utilisateur (dates comprises) telle que
        capacite ∈ capacités(office) − retraits du diocèse
        ET (noeud_nomination = noeud  OU  (office.inherits_down ET noeud_nomination ancêtre de noeud))

L'administrateur plateforme (Numerisen) détient ``PLATFORM_ADMIN_CAPABILITIES`` sur
tout l'arbre. Les « droits » d'un utilisateur sont calculés une fois puis mis en
cache ; la clé inclut la date du jour, une version globale (retraits, offices) et
une version par utilisateur (nominations), invalidées par les services.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q, QuerySet
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from apps.hierarchy.enums import AssignmentStatus
from apps.hierarchy.models import CapabilityOverride, Node, OfficeAssignment
from apps.hierarchy.profiles import CAPABILITIES, PLATFORM_ADMIN_CAPABILITIES

CAPABILITY_CODES = frozenset(c["code"] for c in CAPABILITIES)
CACHE_TTL = 60 * 60
_GLOBAL_VERSION_KEY = "authz:gv"


@dataclass(frozen=True)
class Grant:
    capability: str
    node_id: str | None  # None = toute la plateforme
    node_name: str
    path: str  # "" = racine de tout l'arbre
    inherits: bool
    office: str
    node_type: str = ""  # code du type de nœud ("plateforme" hors arbre), pour grouper les contextes
    office_label: str = ""  # titre de la nomination (« Curé », « Administrateur paroissial »…)

    def covers(self, path: str) -> bool:
        return path == self.path or (self.inherits and path.startswith(self.path))


def _check_capability(capability: str) -> None:
    if capability not in CAPABILITY_CODES:
        raise ValueError(f"Capacité inconnue : {capability!r} (catalogue fermé, RG-14).")


def is_platform_admin(user: Any) -> bool:
    """Administrateur Numerisen : rôle de realm Keycloak ``platform_admin`` (ADR-004), et rien
    d'autre (ni ``is_superuser`` ni l'ancien rôle ``super_admin``)."""
    if not getattr(user, "is_authenticated", False):
        return False
    identity = getattr(user, "keycloak_identity", None)
    return identity is not None and settings.KEYCLOAK_PLATFORM_ADMIN_ROLE in identity.realm_roles


def mfa_satisfied(user: Any) -> bool:
    """EF-AUTH-05 : un titulaire d'office (ou la plateforme) connecté par Keycloak doit l'être avec MFA."""
    identity = getattr(user, "keycloak_identity", None)
    if identity is None or not settings.KEYCLOAK_REQUIRE_MFA_FOR_STAFF:
        return True
    if not grants(user):
        return True  # fidèle : aucun endpoint staff
    return bool(identity.mfa)


def mfa_check(user: Any) -> None:
    if not mfa_satisfied(user):
        raise PermissionDenied(
            "Authentification à deux facteurs requise pour les fonctions de responsable.", code="mfa_required"
        )


def active_assignments(*, user: Any, on: Any = None) -> QuerySet[OfficeAssignment]:
    day = on or timezone.localdate()
    return (
        OfficeAssignment.objects.filter(person=user, status=AssignmentStatus.ACTIVE, start_date__lte=day)
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=day))
        .select_related("node", "node__type", "office_type")
    )


def _grants_compute(user: Any) -> list[Grant]:
    grants: list[Grant] = []
    if is_platform_admin(user):
        grants += [
            Grant(c, None, "Plateforme", "", True, "plateforme", "plateforme", "Administrateur plateforme")
            for c in sorted(PLATFORM_ADMIN_CAPABILITIES)
        ]

    assignments = list(active_assignments(user=user).prefetch_related("office_type__capabilities"))
    if not assignments:
        return grants
    overrides = list(
        CapabilityOverride.objects.filter(office_type_id__in={a.office_type_id for a in assignments}).select_related(
            "diocese_node"
        )
    )
    for a in assignments:
        capabilities = {c.code for c in a.office_type.capabilities.all()}
        for override in overrides:
            if override.office_type_id == a.office_type_id and a.node.path.startswith(override.diocese_node.path):
                capabilities.discard(override.capability_id)
        grants += [
            Grant(
                c,
                str(a.node_id),
                a.node.name,
                a.node.path,
                a.office_type.inherits_down,
                a.office_type.code,
                a.node.type.code,
                a.title,
            )
            for c in sorted(capabilities)
        ]
    return grants


def user_version(user_id: Any) -> int:
    """Version des droits d'un utilisateur : change à chaque nomination ou appartenance à une
    paroisse modifiée (``invalidate_user``). Les caches dérivés (sonothèque) l'incluent dans leur clé."""
    return int(cache.get_or_set(f"authz:uv:{user_id}", 1, None) or 1)


def _cache_key(user: Any) -> str:
    global_version = cache.get_or_set(_GLOBAL_VERSION_KEY, 1, None)
    user_version = cache.get_or_set(f"authz:uv:{user.pk}", 1, None)
    platform = int(is_platform_admin(user))  # le rôle vient du jeton : il fait partie de la clé
    return f"authz:v3:{timezone.localdate().isoformat()}:{global_version}:{user_version}:{platform}:{user.pk}"


def grants(user: Any) -> list[Grant]:
    if not getattr(user, "is_authenticated", False):
        return []
    key = _cache_key(user)
    cached = cache.get(key)
    if cached is None:
        cached = _grants_compute(user)
        cache.set(key, cached, CACHE_TTL)
    return cached


def invalidate_user(user_id: Any) -> None:
    key = f"authz:uv:{user_id}"
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 2, None)


def invalidate_all() -> None:
    try:
        cache.incr(_GLOBAL_VERSION_KEY)
    except ValueError:
        cache.set(_GLOBAL_VERSION_KEY, 2, None)


# --- API publique du moteur --------------------------------------------------------


def peut(user: Any, capacite: str, node: Node | None) -> bool:
    """Vrai si ``user`` détient ``capacite`` sur ``node`` (ou, pour ``node=None``, hors arbre)."""
    _check_capability(capacite)
    relevant = [g for g in grants(user) if g.capability == capacite]
    if node is None:
        return any(g.node_id is None for g in relevant)
    return any(g.covers(node.path) for g in relevant)


def a_la_capacite(user: Any, capacite: str) -> bool:
    """Vrai si ``user`` détient ``capacite`` sur au moins un nœud."""
    _check_capability(capacite)
    return any(g.capability == capacite for g in grants(user))


def noeuds_autorises(user: Any, capacite: str) -> QuerySet[Node]:
    """Tous les nœuds sur lesquels ``user`` détient ``capacite`` (sous-arbres compris)."""
    _check_capability(capacite)
    condition = Q()
    for g in grants(user):
        if g.capability != capacite:
            continue
        if g.node_id is None:
            return Node.objects.all()
        condition |= Q(path__startswith=g.path) if g.inherits else Q(path=g.path)
    if not condition:
        return Node.objects.none()
    return Node.objects.filter(condition)


def capacites(user: Any) -> list[dict[str, Any]]:
    """``[{capacite, node_id, node_name, node_type, herite, office, office_label}]`` pour
    ``GET /me/capacites/`` (EF-PER-10)."""
    return [
        {
            "capacite": g.capability,
            "node_id": g.node_id,
            "node_name": g.node_name,
            "herite": g.inherits,
            "office": g.office,
            "office_label": g.office_label,
            "node_type": g.node_type,
        }
        for g in grants(user)
    ]


# --- Permission DRF -----------------------------------------------------------------

NodeResolver = Callable[[Any, Any], Node | None]


def HasCapability(capability: str, *, node_resolver: NodeResolver | None = None) -> type[BasePermission]:  # noqa: N802
    """Permission DRF. Sans ``node_resolver`` : la capacité sur au moins un nœud suffit
    (la vue filtre ensuite avec ``noeuds_autorises``)."""
    _check_capability(capability)

    class _HasCapability(BasePermission):
        message = "Vous n'avez pas la capacité requise sur ce nœud."

        def has_permission(self, request: Any, view: Any) -> bool:
            user = request.user
            if not getattr(user, "is_authenticated", False):
                return False
            if node_resolver is None:
                allowed = a_la_capacite(user, capability)
            else:
                allowed = peut(user, capability, node_resolver(request, view))
            if allowed:
                mfa_check(user)
            return allowed

    _HasCapability.__name__ = f"HasCapability_{capability.replace('.', '_')}"
    return _HasCapability


def HasAnyCapability(*capabilities: str) -> type[BasePermission]:  # noqa: N802
    """Permission DRF : au moins une des capacités, sur au moins un nœud (MFA exigée)."""
    for capability in capabilities:
        _check_capability(capability)

    class _HasAnyCapability(BasePermission):
        message = "Vous n'avez pas la capacité requise."

        def has_permission(self, request: Any, view: Any) -> bool:
            user = request.user
            if not getattr(user, "is_authenticated", False):
                return False
            allowed = any(a_la_capacite(user, c) for c in capabilities)
            if allowed:
                mfa_check(user)
            return allowed

    _HasAnyCapability.__name__ = "HasAnyCapability_" + "_".join(c.replace(".", "_") for c in capabilities)
    return _HasAnyCapability


def node_from_kwarg(name: str = "node_id") -> NodeResolver:
    def resolve(request: Any, view: Any) -> Node | None:
        return Node.objects.filter(pk=view.kwargs.get(name)).first()

    return resolve
