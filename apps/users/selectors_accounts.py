"""Comptes plateforme (``plateforme.admin``) : liste et fiche.

Données exposées : identité du compte, rôle de realm déduit, MFA, statut, sessions et
offices (libellé, nom du nœud). Jamais de contenu de message ni d'autre donnée religieuse
que le nom du nœud (RG-09, loi 2008-12). Keycloak injoignable : mode dégradé depuis la base.
"""

import datetime
from typing import Any
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import DateTimeField, Exists, F, OuterRef, Prefetch, Q, QuerySet
from django.db.models.functions import Cast, Greatest
from django.utils import timezone

from apps.core.exceptions import NotFoundError
from apps.hierarchy.enums import AssignmentStatus
from apps.hierarchy.models import CapabilityOverride, OfficeAssignment
from apps.users.keycloak_accounts import (
    MFA_NONE,
    MFA_TOTP,
    KeycloakDirectory,
    keycloak_directory,
    keycloak_mfa,
    keycloak_sessions,
)
from apps.users.models import BaseUser

ROLE_PLATFORM_ADMIN = "platform_admin"
ROLE_STAFF = "staff"
ROLE_FIDELE = "fidele"
ROLES = (ROLE_FIDELE, ROLE_STAFF, ROLE_PLATFORM_ADMIN)

STATUS_ACTIF = "actif"
STATUS_VERROUILLE = "verrouille"
STATUS_A_CONFIRMER = "a_confirmer"
STATUSES = (STATUS_ACTIF, STATUS_VERROUILLE, STATUS_A_CONFIRMER)

MFA_FILTER_ACTIVE = "active"
MFA_FILTER_FACULTATIVE = "facultative"
MFA_FILTERS = (MFA_FILTER_ACTIVE, MFA_FILTER_FACULTATIVE)


def _active_assignments(day: datetime.date) -> QuerySet[OfficeAssignment]:
    return OfficeAssignment.objects.filter(status=AssignmentStatus.ACTIVE, start_date__lte=day).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=day)
    )


def _office_exists() -> Exists:
    return Exists(_active_assignments(timezone.localdate()).filter(person=OuterRef("pk")))


def _base_queryset() -> QuerySet[BaseUser]:
    day = timezone.localdate()
    return (
        BaseUser.objects.select_related("profile", "paroisse_suivie")
        .annotate(
            has_office=_office_exists(),
            last_activity=Greatest(F("last_login"), Cast("last_seen_on", DateTimeField())),
        )
        .prefetch_related(
            Prefetch(
                "office_assignments",
                queryset=_active_assignments(day)
                .select_related("node", "office_type")
                .prefetch_related("office_type__capabilities")
                .order_by("start_date", "created_at"),
                to_attr="active_assignments",
            )
        )
    )


# --- Filtres ------------------------------------------------------------------------------


def _subs(directory: KeycloakDirectory | None, predicate: Any) -> list[str]:
    if directory is None:
        return []
    return [sub for sub, account in directory.accounts.items() if predicate(account)]


def _locked_q(directory: KeycloakDirectory | None) -> Q:
    return Q(is_active=False) | Q(keycloak_sub__in=_subs(directory, lambda a: not a.enabled))


def _unconfirmed_q(directory: KeycloakDirectory | None) -> Q:
    known = list(directory.accounts) if directory is not None else []
    return Q(keycloak_sub__in=_subs(directory, lambda a: not a.email_verified)) | (
        ~Q(keycloak_sub__in=known) & Q(is_verified=False)
    )


def _mfa_q(directory: KeycloakDirectory | None) -> Q:
    if directory is None:
        return Q(last_mfa_on__isnull=False)
    return Q(keycloak_sub__in=_subs(directory, lambda a: a.totp))


def _platform_q(directory: KeycloakDirectory | None) -> Q:
    return Q(keycloak_sub__in=sorted(directory.platform_admins) if directory is not None else [])


def account_list(*, filters: dict[str, Any], directory: KeycloakDirectory | None) -> QuerySet[BaseUser]:
    """Comptes filtrés (``q``, ``role``, ``mfa``, ``status``), du plus récemment actif au plus ancien."""
    qs = _base_queryset()
    q = (filters.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(email__icontains=q) | Q(profile__first_name__icontains=q) | Q(profile__last_name__icontains=q))
    role = filters.get("role")
    if role == ROLE_PLATFORM_ADMIN:
        qs = qs.filter(_platform_q(directory))
    elif role == ROLE_STAFF:
        qs = qs.filter(_office_exists()).exclude(_platform_q(directory))
    elif role == ROLE_FIDELE:
        qs = qs.exclude(_office_exists()).exclude(_platform_q(directory))
    mfa = filters.get("mfa")
    if mfa == MFA_FILTER_ACTIVE:
        qs = qs.filter(_mfa_q(directory))
    elif mfa == MFA_FILTER_FACULTATIVE:
        qs = qs.exclude(_mfa_q(directory))
    account_status = filters.get("status")
    if account_status == STATUS_VERROUILLE:
        qs = qs.filter(_locked_q(directory))
    elif account_status == STATUS_A_CONFIRMER:
        qs = qs.exclude(_locked_q(directory)).filter(_unconfirmed_q(directory))
    elif account_status == STATUS_ACTIF:
        qs = qs.exclude(_locked_q(directory)).exclude(_unconfirmed_q(directory))
    return qs.order_by(F("last_activity").desc(nulls_last=True), "-created_at", "pk")


def account_get(*, account_id: UUID | str) -> BaseUser:
    account = _base_queryset().filter(pk=account_id).first()
    if account is None:
        raise NotFoundError("Compte introuvable.", {"account_id": str(account_id)})
    return account


# --- Mise en forme ------------------------------------------------------------------------


def _full_name(user: BaseUser) -> str:
    try:
        profile = user.profile
    except ObjectDoesNotExist:
        return ""
    return f"{profile.first_name} {profile.last_name}".strip()


def _principal_assignment(user: BaseUser) -> OfficeAssignment | None:
    """Nomination principale : la plus haute dans l'arbre, puis la plus ancienne."""
    assignments: list[OfficeAssignment] = getattr(user, "active_assignments", [])
    if not assignments:
        return None
    return min(assignments, key=lambda a: (len(a.node.path), a.start_date))


def _realm_role(user: BaseUser, directory: KeycloakDirectory | None) -> str:
    if directory is not None and user.keycloak_sub in directory.platform_admins:
        return ROLE_PLATFORM_ADMIN
    if getattr(user, "has_office", False):
        return ROLE_STAFF
    return ROLE_FIDELE


def _status(user: BaseUser, directory: KeycloakDirectory | None) -> str:
    kc = directory.accounts.get(user.keycloak_sub or "") if directory is not None else None
    if not user.is_active or (kc is not None and not kc.enabled):
        return STATUS_VERROUILLE
    verified = kc.email_verified if kc is not None else user.is_verified
    return STATUS_ACTIF if verified else STATUS_A_CONFIRMER


def _list_mfa(user: BaseUser, directory: KeycloakDirectory | None) -> str:
    if directory is None:
        return MFA_TOTP if user.last_mfa_on else MFA_NONE
    kc = directory.accounts.get(user.keycloak_sub or "")
    return MFA_TOTP if kc is not None and kc.totp else MFA_NONE


def account_row(*, user: BaseUser, directory: KeycloakDirectory | None) -> dict[str, Any]:
    principal = _principal_assignment(user)
    if principal is not None:
        node_label: str | None = principal.node.name
    else:
        node_label = user.paroisse_suivie.name if user.paroisse_suivie is not None else None
    return {
        "id": user.pk,
        "email": user.email,
        "full_name": _full_name(user),
        "realm_role": _realm_role(user, directory),
        "mfa": _list_mfa(user, directory),
        "last_login": getattr(user, "last_activity", None),
        "status": _status(user, directory),
        "node_label": node_label,
    }


def _offices(user: BaseUser) -> list[dict[str, Any]]:
    assignments: list[OfficeAssignment] = getattr(user, "active_assignments", [])
    overrides = list(
        CapabilityOverride.objects.filter(office_type_id__in={a.office_type_id for a in assignments}).select_related(
            "diocese_node"
        )
    )
    offices = []
    for a in assignments:
        withdrawn = {
            o.capability_id
            for o in overrides
            if o.office_type_id == a.office_type_id and a.node.path.startswith(o.diocese_node.path)
        }
        offices.append(
            {
                "office_label": a.title,
                "node_name": a.node.name,
                "start_date": a.start_date,
                "capabilities": sorted(c.code for c in a.office_type.capabilities.all() if c.code not in withdrawn),
            }
        )
    return offices


def account_detail(*, user: BaseUser) -> dict[str, Any]:
    """Fiche d'un compte. MFA et sessions sont lues en direct dans Keycloak ; à défaut, dégradées."""
    directory = keycloak_directory()
    row = account_row(user=user, directory=directory)
    kc = directory.accounts.get(user.keycloak_sub or "") if directory is not None else None
    sessions: list[dict[str, Any]] = []
    if user.keycloak_sub:
        mfa = keycloak_mfa(user.keycloak_sub)
        if mfa is not None:
            row["mfa"] = mfa
        sessions = keycloak_sessions(user.keycloak_sub) or []
    return {
        **row,
        "keycloak_id": user.keycloak_sub,
        "email_verified": kc.email_verified if kc is not None else bool(user.is_verified),
        "offices": _offices(user),
        "sessions": sessions,
    }
