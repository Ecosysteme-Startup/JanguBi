"""Chaîne de validation des comptes clergé (auto-déclaration).

Couvre :
  - POST /api/v1/users/me/clergy-declaration/  dépôt d'une auto-déclaration
  - GET  /api/v1/users/me/clergy-declaration/  suivi par le demandeur
  - GET  /api/v1/users/pending-validation/     file d'attente + cloisonnement
  - POST /api/v1/users/{id}/validate-account/
  - POST /api/v1/users/{id}/reject-account/
  - les services clergy_declaration_submit / user_validate_clergy_account /
    user_reject_clergy_account

Invariant central vérifié ici : une demande EN ATTENTE n'accorde aucun droit —
``pastoral_role`` reste laïc tant que l'autorité n'a pas approuvé.
"""

import pytest
from rest_framework.test import APIClient

from apps.core.exceptions import ApplicationError
from apps.files.tests.factories import FileFactory, PendingFileFactory
from apps.org.tests.factories import DioceseFactory, ParishFactory
from apps.users.enums import (
    AuditEvent,
    ClergyValidationStatus,
    PastoralRole,
    RoleScope,
    UserRole,
)
from apps.users.models import ClergySelfDeclaration, SecurityAuditLog
from apps.users.permissions import IsOnboardingCompleted
from apps.users.selectors import (
    clergy_declaration_current,
    clergy_pending_validation_list,
)
from apps.users.services_clergy import (
    clergy_declaration_submit,
    user_reject_clergy_account,
    user_validate_clergy_account,
)
from apps.users.tests.factories import (
    BaseUserFactory,
    ProfileFactory,
    RoleAssignmentFactory,
    SuperAdminFactory,
)

PENDING_URL = "/api/v1/users/pending-validation/"
DECLARATION_URL = "/api/v1/users/me/clergy-declaration/"


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _declare(*, user, parish, pastoral_role=PastoralRole.PRETRE, message=""):
    """Dépose une auto-déclaration pour ``user`` via le service réel."""
    return clergy_declaration_submit(
        user=user,
        claimed_pastoral_role=pastoral_role,
        parish_id=parish.id,
        justification_file_id=FileFactory(uploaded_by=user).id,
        message=message,
    )


def _pending_clergy(*, parish=None, pastoral_role=PastoralRole.PRETRE, diocese=None):
    """Un compte ayant déposé une auto-déclaration, en attente de décision.

    Le compte reste délibérément ``pastoral_role=None`` : c'est l'état réel d'un
    candidat en attente, et le cœur de la garantie anti-escalade.
    """
    user = BaseUserFactory(role=UserRole.FIDELE, diocese=diocese)
    ProfileFactory(user=user, primary_parish=parish)
    _declare(user=user, parish=parish or ParishFactory(), pastoral_role=pastoral_role)
    user.refresh_from_db()
    return user


def _bishop_of(diocese):
    """Un évêque porteur d'une RoleAssignment active sur son diocèse."""
    bishop = BaseUserFactory(role=UserRole.FIDELE, pastoral_role=PastoralRole.EVEQUE)
    RoleAssignmentFactory(
        user=bishop,
        role=UserRole.DIOCESE_ADMIN,
        scope=RoleScope.DIOCESE,
        diocese=diocese,
        parish=None,
    )
    return bishop


# ---------------------------------------------------------------------------
# Selector — file d'attente + cloisonnement
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_pending_list_contains_only_pending_clergy():
    # Arrange
    pending = _pending_clergy()
    BaseUserFactory(  # clergé déjà validé (voie invitation)
        pastoral_role=PastoralRole.PRETRE,
        clergy_validation_status=ClergyValidationStatus.APPROVED,
    )
    BaseUserFactory()  # laïc

    # Act
    result = list(clergy_pending_validation_list(admin=SuperAdminFactory()))

    # Assert
    assert [u.id for u in result] == [pending.id]


@pytest.mark.django_db
def test_pending_list_is_scoped_to_bishop_diocese():
    # Arrange — deux diocèses, un candidat dans chacun
    diocese_a, diocese_b = DioceseFactory(), DioceseFactory()
    mine = _pending_clergy(parish=ParishFactory(diocese=diocese_a))
    _pending_clergy(parish=ParishFactory(diocese=diocese_b))
    bishop = _bishop_of(diocese_a)

    # Act
    result = list(clergy_pending_validation_list(admin=bishop))

    # Assert — le clergé du diocèse B est invisible
    assert [u.id for u in result] == [mine.id]


@pytest.mark.django_db
def test_pending_list_fails_closed_without_territorial_assignment():
    # Un évêque sans RoleAssignment n'a autorité sur personne (fail-closed).
    # Arrange
    _pending_clergy(parish=ParishFactory())
    bishop_without_scope = BaseUserFactory(pastoral_role=PastoralRole.EVEQUE)

    # Act
    result = list(clergy_pending_validation_list(admin=bishop_without_scope))

    # Assert
    assert result == []


# ---------------------------------------------------------------------------
# Service — approbation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_validate_activates_account_and_audits():
    # Arrange
    candidate = _pending_clergy()
    admin = SuperAdminFactory()

    # Act
    result = user_validate_clergy_account(user=candidate, performed_by=admin)

    # Assert
    result.refresh_from_db()
    assert result.clergy_validation_status == ClergyValidationStatus.APPROVED
    assert result.is_active is True
    assert result.is_verified is True
    assert SecurityAuditLog.objects.filter(
        user=candidate, event=AuditEvent.CLERGY_ACCOUNT_APPROVED
    ).exists()


@pytest.mark.django_db
def test_validate_rejects_non_pending_account():
    # Arrange
    already = BaseUserFactory(
        pastoral_role=PastoralRole.PRETRE,
        clergy_validation_status=ClergyValidationStatus.APPROVED,
    )

    # Act & Assert
    with pytest.raises(ApplicationError):
        user_validate_clergy_account(user=already, performed_by=SuperAdminFactory())


@pytest.mark.django_db
def test_validate_rejects_non_clergy_account():
    # Arrange
    laic = BaseUserFactory(clergy_validation_status=ClergyValidationStatus.PENDING)

    # Act & Assert
    with pytest.raises(ApplicationError):
        user_validate_clergy_account(user=laic, performed_by=SuperAdminFactory())


@pytest.mark.django_db
def test_bishop_cannot_validate_out_of_his_diocese():
    # Arrange
    diocese_a, diocese_b = DioceseFactory(), DioceseFactory()
    candidate = _pending_clergy(parish=ParishFactory(diocese=diocese_b))
    bishop = _bishop_of(diocese_a)

    # Act & Assert — cloisonnement territorial fail-closed
    with pytest.raises(ApplicationError):
        user_validate_clergy_account(user=candidate, performed_by=bishop)


@pytest.mark.django_db
def test_bishop_cannot_validate_another_bishop():
    # Nommer un évêque relève du seul super_admin.
    # Arrange
    diocese = DioceseFactory()
    candidate = _pending_clergy(
        parish=ParishFactory(diocese=diocese), pastoral_role=PastoralRole.EVEQUE
    )
    bishop = _bishop_of(diocese)

    # Act & Assert
    with pytest.raises(ApplicationError):
        user_validate_clergy_account(user=candidate, performed_by=bishop)


@pytest.mark.django_db
def test_bishop_validates_priest_of_his_diocese():
    # Arrange
    diocese = DioceseFactory()
    candidate = _pending_clergy(parish=ParishFactory(diocese=diocese))
    bishop = _bishop_of(diocese)

    # Act
    result = user_validate_clergy_account(user=candidate, performed_by=bishop)

    # Assert
    assert result.clergy_validation_status == ClergyValidationStatus.APPROVED


# ---------------------------------------------------------------------------
# Service — refus
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_reject_requires_a_reason():
    # Arrange
    candidate = _pending_clergy()

    # Act & Assert
    with pytest.raises(ApplicationError):
        user_reject_clergy_account(
            user=candidate, reason="   ", performed_by=SuperAdminFactory()
        )


@pytest.mark.django_db
def test_reject_strips_pastoral_role_and_records_reason():
    # Arrange
    candidate = _pending_clergy()
    admin = SuperAdminFactory()

    # Act
    result = user_reject_clergy_account(
        user=candidate, reason="Aucun justificatif fourni.", performed_by=admin
    )

    # Assert — le rôle clérical revendiqué est retiré (il ouvrait des écritures)
    result.refresh_from_db()
    assert result.clergy_validation_status == ClergyValidationStatus.REJECTED
    assert result.pastoral_role == PastoralRole.FIDELE

    log = SecurityAuditLog.objects.get(
        user=candidate, event=AuditEvent.CLERGY_ACCOUNT_REJECTED
    )
    assert log.metadata["reason"] == "Aucun justificatif fourni."
    assert log.metadata["claimed_pastoral_role"] == PastoralRole.PRETRE


@pytest.mark.django_db
def test_rejected_account_leaves_the_pending_queue():
    # Arrange
    candidate = _pending_clergy()
    admin = SuperAdminFactory()

    # Act
    user_reject_clergy_account(user=candidate, reason="Motif.", performed_by=admin)

    # Assert
    assert list(clergy_pending_validation_list(admin=admin)) == []


# ---------------------------------------------------------------------------
# APIs
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Auto-déclaration — l'invariant anti-escalade de privilèges
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_pending_declaration_grants_no_pastoral_role():
    """Le point critique : revendiquer n'est pas obtenir.

    ``pastoral_role`` est lu SEUL — sans jamais consulter clergy_validation_status
    — par la signature de documents, la publication d'actualités, la messagerie
    inter-clergé, les intentions de messe, les dons, la TV Formation. S'il était
    posé au dépôt, l'auto-déclaration serait une escalade en libre-service.
    """
    # Arrange
    user = BaseUserFactory(role=UserRole.FIDELE)
    ProfileFactory(user=user)

    # Act
    _declare(user=user, parish=ParishFactory())

    # Assert
    user.refresh_from_db()
    assert user.pastoral_role is None
    assert user.clergy_validation_status == ClergyValidationStatus.PENDING


@pytest.mark.django_db
def test_pending_declaration_does_not_open_territorial_writes():
    # Corollaire concret : la garde canonique des écritures territoriales
    # (IsOnboardingCompleted) laisse passer tout porteur de pastoral_role clérical.
    # Arrange
    user = BaseUserFactory(role=UserRole.FIDELE)
    ProfileFactory(user=user)
    _declare(user=user, parish=ParishFactory())
    user.refresh_from_db()

    class _Req:
        pass

    request = _Req()
    request.user = user

    # Act & Assert — onboarding non terminé + non admin + non clergé ⇒ refusé
    assert IsOnboardingCompleted().has_permission(request, None) is False


@pytest.mark.django_db
def test_approval_is_what_grants_the_pastoral_role():
    # Arrange
    diocese = DioceseFactory()
    parish = ParishFactory(diocese=diocese)
    candidate = _pending_clergy(parish=parish)
    bishop = _bishop_of(diocese)

    # Act
    result = user_validate_clergy_account(user=candidate, performed_by=bishop)

    # Assert — le rôle n'existe qu'à partir de la décision humaine
    result.refresh_from_db()
    assert result.pastoral_role == PastoralRole.PRETRE
    assert result.clergy_validation_status == ClergyValidationStatus.APPROVED
    declaration = clergy_declaration_current(user=result)
    assert declaration.status == ClergySelfDeclaration.Status.APPROVED
    assert declaration.reviewed_by == bishop
    assert declaration.reviewed_at is not None


@pytest.mark.django_db
def test_approval_grants_no_administrative_capacity():
    # Reconnaître une identité pastorale n'est pas nommer un curé titulaire.
    # Arrange
    candidate = _pending_clergy()

    # Act
    user_validate_clergy_account(user=candidate, performed_by=SuperAdminFactory())

    # Assert
    assert candidate.role_assignments.count() == 0


# ---------------------------------------------------------------------------
# Auto-déclaration — service de dépôt
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_declaration_appears_in_the_validation_queue():
    # La raison d'être de ce chantier : sans auto-déclaration, la file est vide.
    # Arrange
    diocese = DioceseFactory()
    parish = ParishFactory(diocese=diocese)
    user = BaseUserFactory(role=UserRole.FIDELE)
    ProfileFactory(user=user)

    # Act
    _declare(user=user, parish=parish)

    # Assert
    assert [u.id for u in clergy_pending_validation_list(admin=_bishop_of(diocese))] == [user.id]


@pytest.mark.django_db
def test_declaration_visible_to_bishop_even_without_primary_parish():
    """Le cloisonnement porte sur la paroisse REVENDIQUÉE, pas celle du profil.

    Un candidat dont l'onboarding fidèle n'est pas terminé n'a pas de paroisse
    principale : scoper sur le profil l'aurait rendu invisible de son évêque et
    la file serait restée vide pour l'autorité compétente.
    """
    # Arrange
    diocese = DioceseFactory()
    user = BaseUserFactory(role=UserRole.FIDELE)
    ProfileFactory(user=user, primary_parish=None)
    _declare(user=user, parish=ParishFactory(diocese=diocese))

    # Act
    result = list(clergy_pending_validation_list(admin=_bishop_of(diocese)))

    # Assert
    assert [u.id for u in result] == [user.id]


@pytest.mark.django_db
def test_declaration_rejects_invalid_file():
    # Un fichier dont l'upload n'est pas terminé n'a pas de contenu : la demande
    # partirait sans preuve.
    # Arrange
    user = BaseUserFactory()
    pending_file = PendingFileFactory(uploaded_by=user)

    # Act & Assert
    with pytest.raises(ApplicationError):
        clergy_declaration_submit(
            user=user,
            claimed_pastoral_role=PastoralRole.PRETRE,
            parish_id=ParishFactory().id,
            justification_file_id=pending_file.id,
        )


@pytest.mark.django_db
def test_declaration_rejects_someone_elses_file():
    # Arrange
    user = BaseUserFactory()
    someone_else_file = FileFactory(uploaded_by=BaseUserFactory())

    # Act & Assert
    with pytest.raises(ApplicationError):
        clergy_declaration_submit(
            user=user,
            claimed_pastoral_role=PastoralRole.PRETRE,
            parish_id=ParishFactory().id,
            justification_file_id=someone_else_file.id,
        )


@pytest.mark.django_db
def test_declaration_rejects_unknown_parish():
    user = BaseUserFactory()
    with pytest.raises(ApplicationError):
        clergy_declaration_submit(
            user=user,
            claimed_pastoral_role=PastoralRole.PRETRE,
            parish_id=999999,
            justification_file_id=FileFactory(uploaded_by=user).id,
        )


@pytest.mark.django_db
def test_declaration_rejects_a_non_clergy_role():
    user = BaseUserFactory()
    with pytest.raises(ApplicationError):
        clergy_declaration_submit(
            user=user,
            claimed_pastoral_role=PastoralRole.FIDELE,
            parish_id=ParishFactory().id,
            justification_file_id=FileFactory(uploaded_by=user).id,
        )


@pytest.mark.django_db
def test_resubmission_blocked_while_pending():
    # Arrange
    user = BaseUserFactory()
    ProfileFactory(user=user)
    _declare(user=user, parish=ParishFactory())

    # Act & Assert
    with pytest.raises(ApplicationError):
        _declare(user=user, parish=ParishFactory())


@pytest.mark.django_db
def test_resubmission_allowed_after_a_rejection():
    # Un refus doit rester corrigeable : sinon le compte est bloqué à vie.
    # Arrange
    user = _pending_clergy()
    user_reject_clergy_account(
        user=user, reason="Justificatif illisible.", performed_by=SuperAdminFactory()
    )
    user.refresh_from_db()

    # Act
    declaration = _declare(user=user, parish=ParishFactory())

    # Assert
    assert declaration.status == ClergySelfDeclaration.Status.PENDING
    user.refresh_from_db()
    assert user.clergy_validation_status == ClergyValidationStatus.PENDING


@pytest.mark.django_db
def test_declaration_blocked_for_already_validated_clergy():
    # Arrange — compte issu de la voie invitation (naît APPROVED)
    user = BaseUserFactory(
        pastoral_role=PastoralRole.PRETRE,
        clergy_validation_status=ClergyValidationStatus.APPROVED,
    )

    # Act & Assert
    with pytest.raises(ApplicationError):
        _declare(user=user, parish=ParishFactory())


@pytest.mark.django_db
def test_rejection_reason_is_readable_by_the_requester():
    # Arrange
    user = _pending_clergy()

    # Act
    user_reject_clergy_account(
        user=user, reason="Attestation non signée.", performed_by=SuperAdminFactory()
    )

    # Assert — le demandeur doit pouvoir lire le motif pour corriger
    declaration = clergy_declaration_current(user=user)
    assert declaration.status == ClergySelfDeclaration.Status.REJECTED
    assert declaration.rejection_reason == "Attestation non signée."


@pytest.mark.django_db
def test_declaration_audits_and_notifies_requester():
    # Arrange
    from apps.emails.models import Email

    user = BaseUserFactory()
    ProfileFactory(user=user)

    # Act
    _declare(user=user, parish=ParishFactory())

    # Assert
    assert SecurityAuditLog.objects.filter(
        user=user, event=AuditEvent.CLERGY_DECLARATION_SUBMITTED
    ).exists()
    assert Email.objects.filter(to=user.email).exists()


@pytest.mark.django_db
def test_declaration_notifies_the_competent_bishop():
    # Sans cette alerte, la file se remplit sans que personne ne le sache.
    # Arrange
    from apps.emails.models import Email

    diocese = DioceseFactory()
    bishop = _bishop_of(diocese)
    user = BaseUserFactory()
    ProfileFactory(user=user)

    # Act
    _declare(user=user, parish=ParishFactory(diocese=diocese))

    # Assert
    assert Email.objects.filter(to=bishop.email).exists()


@pytest.mark.django_db
def test_declaration_does_not_notify_a_bishop_of_another_diocese():
    # Arrange
    from apps.emails.models import Email

    diocese_a, diocese_b = DioceseFactory(), DioceseFactory()
    outsider = _bishop_of(diocese_b)
    user = BaseUserFactory()
    ProfileFactory(user=user)

    # Act
    _declare(user=user, parish=ParishFactory(diocese=diocese_a))

    # Assert
    assert not Email.objects.filter(to=outsider.email).exists()


# ---------------------------------------------------------------------------
# Auto-déclaration — API côté demandeur
# ---------------------------------------------------------------------------
