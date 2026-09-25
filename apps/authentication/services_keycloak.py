"""Synchronisation du rôle ``staff`` et migration des comptes vers Keycloak (EF-AUTH-04, -06)."""

import logging
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction

from apps.authentication.keycloak_admin import KeycloakAdmin, django_hash_to_keycloak_credential

logger = logging.getLogger(__name__)


def keycloak_staff_role_sync(*, person: Any, admin: KeycloakAdmin | None = None) -> str:
    """Rôle ``staff`` si et seulement si la personne a une nomination active. À l'ajout, la
    configuration de l'OTP devient une action requise (la MFA sera exigée à la connexion)."""
    from apps.hierarchy.authz import active_assignments

    if not settings.KEYCLOAK_ENABLED or not person.keycloak_sub:
        return "skipped"
    admin = admin or KeycloakAdmin()
    has_office = active_assignments(user=person).exists()
    roles = admin.user_realm_roles(person.keycloak_sub)
    staff = settings.KEYCLOAK_STAFF_ROLE
    if has_office and staff not in roles:
        admin.add_realm_role(person.keycloak_sub, staff)
        if not admin.user_has_otp(person.keycloak_sub):
            admin.add_required_action(person.keycloak_sub, "CONFIGURE_TOTP")
        return "added"
    if not has_office and staff in roles:
        admin.remove_realm_role(person.keycloak_sub, staff)
        return "removed"
    return "unchanged"


def keycloak_staff_reconcile(*, admin: KeycloakAdmin | None = None) -> dict[str, int]:
    """Réconciliation nocturne : titulaires d'office et membres actuels du rôle ``staff``."""
    from apps.hierarchy.models import OfficeAssignment

    if not settings.KEYCLOAK_ENABLED:
        return {}
    admin = admin or KeycloakAdmin()
    User = get_user_model()
    subs = set(admin.role_members(settings.KEYCLOAK_STAFF_ROLE))
    people = User.objects.filter(keycloak_sub__isnull=False).filter(
        pk__in=OfficeAssignment.objects.values("person_id")
    ) | User.objects.filter(keycloak_sub__in=subs)
    counts: dict[str, int] = {}
    for person in people.distinct():
        result = keycloak_staff_role_sync(person=person, admin=admin)
        counts[result] = counts.get(result, 0) + 1
    return counts


# --- Migration des comptes -------------------------------------------------------------


@dataclass
class MigrationLine:
    email: str
    action: str  # creer | lier | deja_lie | ignorer
    password: str  # importe | reinitialisation | sans_objet
    keycloak_id: str = ""


def _representation(user: Any) -> dict[str, Any]:
    profile = getattr(user, "profile", None)
    rep: dict[str, Any] = {
        "username": user.email,
        "email": user.email,
        "emailVerified": bool(user.is_verified),
        "enabled": bool(user.is_active),
        "firstName": getattr(profile, "first_name", "") or "",
        "lastName": getattr(profile, "last_name", "") or "",
        "attributes": {"jangubi_id": [str(user.pk)]},
    }
    credential = django_hash_to_keycloak_credential(user.password or "")
    if credential is not None:
        rep["credentials"] = [credential]
    else:
        rep["requiredActions"] = ["UPDATE_PASSWORD"]
    return rep


def users_to_keycloak_migrate(
    *, apply: bool = False, admin: KeycloakAdmin | None = None, limit: int | None = None
) -> list[MigrationLine]:
    """Simulation par défaut. Idempotent : un compte déjà lié (``keycloak_sub``) est sauté,
    un e-mail déjà présent dans Keycloak est lié sans être recréé."""
    User = get_user_model()
    lines: list[MigrationLine] = []
    qs = User.objects.select_related("profile").order_by("created_at")
    if limit:
        qs = qs[:limit]
    for user in qs:
        password = "importe" if django_hash_to_keycloak_credential(user.password or "") else "reinitialisation"
        if user.keycloak_sub:
            lines.append(MigrationLine(user.email, "deja_lie", "sans_objet", user.keycloak_sub))
            continue
        if not user.is_active and not user.is_verified:
            lines.append(MigrationLine(user.email, "ignorer", "sans_objet"))
            continue
        if not apply:
            lines.append(MigrationLine(user.email, "creer", password))
            continue
        admin = admin or KeycloakAdmin()
        keycloak_id, created = admin.user_create(_representation(user))
        with transaction.atomic():
            User.objects.filter(pk=user.pk, keycloak_sub__isnull=True).update(keycloak_sub=keycloak_id)
        lines.append(MigrationLine(user.email, "creer" if created else "lier", password, keycloak_id))
    return lines
