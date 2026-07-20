"""Renvoi de l'email de vérification.

Contexte (audit beta 2026-07-20) : un compte est créé `is_active=False` et n'est
activé que par le lien reçu par email, valable 24 h. Sans moyen de renvoi, tout
testeur ayant perdu ou laissé expirer son email était définitivement bloqué —
la réinscription étant refusée (« un compte avec cet email existe déjà »), la
seule issue était une intervention manuelle en base.

Le service suit le contrat de `password_reset_request` : réponse TOUJOURS
identique quelle que soit l'existence du compte (anti-énumération), plus un
rate-limit.
"""

import pytest

from apps.core.exceptions import OtpRateLimitError
from apps.emails.models import Email
from apps.users.enums import UserOnboardingState
from apps.users.services import user_register_fidele, verification_email_resend

from .factories import BaseUserFactory


@pytest.fixture
def unverified_user(db):
    return user_register_fidele(
        email="testeur@example.com",
        phone_number="+221770000001",
        password="Un-Mot-De-Passe-Solide-1",
        first_name="Awa",
        last_name="Diop",
        title="MRS",
    )


@pytest.mark.django_db
def test_renvoi_envoie_un_nouvel_email_a_un_compte_non_verifie(unverified_user):
    # Arrange
    # Les emails ne partent pas en direct : ils sont PERSISTÉS en base puis
    # dispatchés par Celery (apps/emails/services.py) — `mailoutbox` reste donc
    # vide en test, c'est bien l'enregistrement Email qu'il faut observer.
    nb_avant = Email.objects.filter(to=unverified_user.email).count()

    # Act
    verification_email_resend(email=unverified_user.email)

    # Assert
    assert Email.objects.filter(to=unverified_user.email).count() == nb_avant + 1


@pytest.mark.django_db
def test_le_nouveau_lien_active_bien_le_compte(unverified_user):
    """Le jeton renvoyé doit être exploitable de bout en bout."""
    # Arrange
    from apps.users.services import user_activate_account

    verification_email_resend(email=unverified_user.email)
    corps = Email.objects.filter(to=unverified_user.email).latest("created_at").plain_text
    token = corps.split("verify-email?token=")[1].split()[0].strip().rstrip(">).,\"'")

    # Act
    user = user_activate_account(token=token)

    # Assert
    user.refresh_from_db()
    assert user.is_active is True
    assert user.is_verified is True
    assert user.onboarding_state == UserOnboardingState.PENDING_PARISH_SELECTION


@pytest.mark.django_db
def test_aucun_email_pour_un_compte_deja_verifie():
    """Un compte actif n'a rien à réactiver — et on ne le lui dit pas."""
    # Arrange
    user = BaseUserFactory(is_active=True, is_verified=True)

    # Act
    verification_email_resend(email=user.email)

    # Assert
    assert Email.objects.filter(to=user.email).count() == 0


@pytest.mark.django_db
def test_adresse_inconnue_ne_leve_rien_et_n_envoie_rien():
    """Anti-énumération : le comportement observable est identique."""
    # Act — ne doit PAS lever
    verification_email_resend(email="personne@example.com")

    # Assert
    assert Email.objects.filter(to="personne@example.com").count() == 0


@pytest.mark.django_db
def test_rate_limit_au_dela_de_cinq_demandes(unverified_user):
    # Arrange
    ip = "203.0.113.9"

    # Act & Assert
    for _ in range(5):
        verification_email_resend(email=unverified_user.email, ip=ip)

    with pytest.raises(OtpRateLimitError):
        verification_email_resend(email=unverified_user.email, ip=ip)
