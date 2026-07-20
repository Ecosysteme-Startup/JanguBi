"""Garde-fous contre l'escalade de privilèges via RoleAssignment.

Contexte (audit beta 2026-07-20) : ``is_global_admin`` ne filtrait que sur le
RÔLE, jamais sur la PORTÉE. Une ``RoleAssignment(role=super_admin,
scope=parish)`` — créable par n'importe quel admin de paroisse sur sa propre
paroisse, pour lui-même — suffisait donc à obtenir l'autorité globale sur toute
la plateforme.

Deux verrous indépendants sont testés ici :
1. ``role_assignment_create`` refuse le couple rôle/portée incohérent (empêche
   la création de la ligne) ;
2. ``is_global_admin`` exige ``scope=GLOBAL`` (neutralise une ligne existante,
   par exemple créée avant ce correctif ou insérée hors service).
"""

import pytest

from apps.core.exceptions import ApplicationError
from apps.org.tests.factories import ChurchFactory, DioceseFactory, ParishFactory, ProvinceFactory
from apps.users.enums import RoleScope, UserRole
from apps.users.models import RoleAssignment
from apps.users.scoping import is_global_admin
from apps.users.services_roles import role_assignment_create

from .factories import BaseUserFactory

# ---------------------------------------------------------------------------
# Verrou 1 — le service refuse un couple rôle/portée incohérent
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_role_assignment_create_refuse_super_admin_scope_parish():
    """Le scénario d'escalade exact : super_admin scopé à une paroisse."""
    # Arrange
    user = BaseUserFactory(role=UserRole.PARISH_ADMIN)
    parish = ParishFactory()

    # Act & Assert
    with pytest.raises(ApplicationError):
        role_assignment_create(
            user=user,
            role=UserRole.SUPER_ADMIN,
            scope=RoleScope.PARISH,
            parish=parish,
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role",
    [UserRole.SUPER_ADMIN, UserRole.PROVINCE_ADMIN, UserRole.DIOCESE_ADMIN],
)
def test_role_assignment_create_refuse_role_trop_large_pour_la_portee(role):
    """Un admin de paroisse ne peut pas non plus accorder diocèse/province."""
    # Arrange
    user = BaseUserFactory()
    parish = ParishFactory()

    # Act & Assert
    with pytest.raises(ApplicationError):
        role_assignment_create(user=user, role=role, scope=RoleScope.PARISH, parish=parish)


@pytest.mark.django_db
def test_role_assignment_create_refuse_role_territorial_en_portee_globale():
    """Symétrique : un rôle territorial ne s'accorde pas en portée globale."""
    # Arrange
    user = BaseUserFactory()

    # Act & Assert
    with pytest.raises(ApplicationError):
        role_assignment_create(user=user, role=UserRole.PARISH_ADMIN, scope=RoleScope.GLOBAL)


# ---------------------------------------------------------------------------
# Les couples légitimes restent acceptés (non-régression)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_couples_legitimes_restent_acceptes():
    # Arrange
    province = ProvinceFactory()
    diocese = DioceseFactory(province=province)
    parish = ParishFactory(diocese=diocese)
    church = ChurchFactory(parish=parish)

    # Act & Assert — aucune exception attendue
    role_assignment_create(
        user=BaseUserFactory(), role=UserRole.SUPER_ADMIN, scope=RoleScope.GLOBAL
    )
    role_assignment_create(
        user=BaseUserFactory(), role=UserRole.PROVINCE_ADMIN,
        scope=RoleScope.PROVINCE, province=province,
    )
    role_assignment_create(
        user=BaseUserFactory(), role=UserRole.DIOCESE_ADMIN,
        scope=RoleScope.DIOCESE, diocese=diocese,
    )
    role_assignment_create(
        user=BaseUserFactory(), role=UserRole.PARISH_ADMIN,
        scope=RoleScope.PARISH, parish=parish,
    )
    role_assignment_create(
        user=BaseUserFactory(), role=UserRole.CHURCH_ADMIN,
        scope=RoleScope.CHURCH, church=church,
    )


@pytest.mark.django_db
def test_church_admin_scope_parish_reste_accepte():
    """Cas réel produit par la migration de backfill 0004 : un church_admin est
    rattaché à la PAROISSE quand aucune église principale n'existe."""
    # Arrange
    parish = ParishFactory()

    # Act & Assert — aucune exception attendue
    role_assignment_create(
        user=BaseUserFactory(), role=UserRole.CHURCH_ADMIN,
        scope=RoleScope.PARISH, parish=parish,
    )


# ---------------------------------------------------------------------------
# Verrou 2 — is_global_admin exige la portée GLOBAL
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_is_global_admin_ignore_une_affectation_super_admin_mal_scopee():
    """Défense en profondeur : même une ligne déjà en base (créée avant ce
    correctif, ou insérée hors service) ne doit pas conférer l'autorité globale.

    On écrit donc directement via l'ORM, en contournant volontairement le
    service — c'est exactement l'état que le correctif doit neutraliser.
    """
    # Arrange
    user = BaseUserFactory(role=UserRole.PARISH_ADMIN)
    parish = ParishFactory()
    RoleAssignment.objects.create(
        user=user,
        role=UserRole.SUPER_ADMIN,
        scope=RoleScope.PARISH,
        parish=parish,
        is_active=True,
    )

    # Act & Assert
    assert is_global_admin(user) is False


@pytest.mark.django_db
def test_is_global_admin_reconnait_une_affectation_globale_valide():
    # Arrange
    user = BaseUserFactory()
    role_assignment_create(user=user, role=UserRole.SUPER_ADMIN, scope=RoleScope.GLOBAL)

    # Act & Assert
    assert is_global_admin(user) is True


@pytest.mark.django_db
def test_is_global_admin_reconnait_le_role_direct_sur_le_compte():
    """Non-régression : ``user.role = super_admin`` reste une voie valide."""
    # Arrange
    user = BaseUserFactory(role=UserRole.SUPER_ADMIN)

    # Act & Assert
    assert is_global_admin(user) is True
