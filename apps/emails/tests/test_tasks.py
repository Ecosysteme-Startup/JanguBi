"""
Tests for apps/emails/tasks.py — chemin critique de TOUTE notification.

Pattern AAA (Arrange / Act / Assert). Aucun SMTP réel n'est jamais appelé.

Deux régressions sont verrouillées ici :
  1. le retry doit être BORNÉ (sinon boucle infinie → saturation RabbitMQ) ;
  2. le handler d'échec ne doit JAMAIS lever (sinon l'Email reste bloqué en
     SENDING et la trace de l'erreur d'origine est masquée).
"""

from unittest.mock import MagicMock, patch

import pytest

from apps.emails.models import Email
from apps.emails.tasks import (
    EMAIL_SEND_MAX_RETRIES,
    EMAIL_SEND_RETRY_BASE_DELAY,
    EMAIL_SEND_RETRY_MAX_DELAY,
    _email_send_failure,
    _retry_countdown,
    email_send,
)

from .factories import EmailFactory, SendingEmailFactory, SentEmailFactory

# ---------------------------------------------------------------------------
# Backoff — fonction pure, aucun accès DB
# ---------------------------------------------------------------------------


def test_retry_countdown_starts_at_base_delay():
    # Arrange / Act / Assert — première tentative (0 retry déjà effectué)
    assert _retry_countdown(0) == EMAIL_SEND_RETRY_BASE_DELAY


def test_retry_countdown_grows_exponentially():
    # Arrange / Act
    delays = [_retry_countdown(n) for n in range(4)]

    # Assert — chaque délai double le précédent (tant que le plafond n'est pas atteint)
    assert delays == [
        EMAIL_SEND_RETRY_BASE_DELAY,
        EMAIL_SEND_RETRY_BASE_DELAY * 2,
        EMAIL_SEND_RETRY_BASE_DELAY * 4,
        EMAIL_SEND_RETRY_BASE_DELAY * 8,
    ]


def test_retry_countdown_is_capped():
    # Arrange / Act — un très grand nombre de tentatives
    delay = _retry_countdown(99)

    # Assert — le backoff ne dépasse jamais le plafond (pas d'overflow de délai)
    assert delay == EMAIL_SEND_RETRY_MAX_DELAY


def test_email_send_task_has_bounded_max_retries():
    """RÉGRESSION : sans max_retries, self.retry boucle indéfiniment."""
    # Arrange / Act / Assert
    assert email_send.max_retries is not None
    assert email_send.max_retries == EMAIL_SEND_MAX_RETRIES


# ---------------------------------------------------------------------------
# email_send — chemin nominal
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_email_send_task_marks_email_as_sent():
    # Arrange
    email = SendingEmailFactory()

    # Act
    with patch("apps.emails.services.EmailMultiAlternatives") as mock_msg_class:
        mock_msg_class.return_value = MagicMock()
        email_send.apply(args=[email.id])

    # Assert
    email.refresh_from_db()
    assert email.status == Email.Status.SENT
    assert email.sent_at is not None


@pytest.mark.django_db
def test_email_send_task_calls_the_service_with_the_email():
    # Arrange
    email = SendingEmailFactory()

    # Act
    with patch("apps.emails.services.email_send") as mock_service:
        email_send.apply(args=[email.id])

    # Assert — la tâche délègue au service, elle ne parle pas à SMTP elle-même
    mock_service.assert_called_once()
    assert mock_service.call_args.args[0].id == email.id


# ---------------------------------------------------------------------------
# email_send — retry borné
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_email_send_task_retries_with_backoff_countdown_on_failure():
    # Arrange
    email = SendingEmailFactory()

    # Act — le service échoue ; on capture l'appel à retry sans le laisser rejouer
    with (
        patch("apps.emails.services.email_send", side_effect=RuntimeError("SMTP down")),
        patch.object(email_send, "retry") as mock_retry,
    ):
        email_send.apply(args=[email.id], throw=False)

    # Assert — retry demandé avec un countdown de backoff (et non 5 s en boucle)
    mock_retry.assert_called_once()
    assert mock_retry.call_args.kwargs["countdown"] == EMAIL_SEND_RETRY_BASE_DELAY
    assert isinstance(mock_retry.call_args.kwargs["exc"], RuntimeError)


@pytest.mark.django_db
def test_email_send_task_marks_email_failed_when_retries_are_exhausted():
    """Quand Celery a épuisé max_retries, il relève l'exception d'origine :
    la tâche échoue et le handler bascule l'Email en FAILED."""
    # Arrange
    email = SendingEmailFactory()

    # Act — retry relève l'exception (comportement Celery une fois max_retries atteint)
    with (
        patch("apps.emails.services.email_send", side_effect=RuntimeError("SMTP down")),
        patch.object(email_send, "retry", side_effect=RuntimeError("SMTP down")),
    ):
        result = email_send.apply(args=[email.id], throw=False)

    # Assert
    assert result.failed()
    email.refresh_from_db()
    assert email.status == Email.Status.FAILED


# ---------------------------------------------------------------------------
# _email_send_failure — le handler ne doit JAMAIS lever
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_failure_handler_marks_email_as_failed():
    # Arrange
    email = SendingEmailFactory()

    # Act
    _email_send_failure(MagicMock(), RuntimeError("boom"), "task-id", [email.id], {}, None)

    # Assert
    email.refresh_from_db()
    assert email.status == Email.Status.FAILED


@pytest.mark.django_db
def test_failure_handler_does_not_raise_when_email_was_deleted():
    """RÉGRESSION : Email.objects.get() sans garde levait DoesNotExist DANS le
    handler — l'état ne passait jamais à FAILED et l'erreur d'origine était masquée."""
    # Arrange — id d'un Email qui n'existe plus
    email = SendingEmailFactory()
    deleted_id = email.id
    email.delete()

    # Act & Assert — aucune exception ne doit sortir du handler
    _email_send_failure(MagicMock(), RuntimeError("boom"), "task-id", [deleted_id], {}, None)


@pytest.mark.django_db
def test_failure_handler_does_not_raise_when_email_is_not_sending():
    """email_failed lève ApplicationError hors statut SENDING : le handler l'absorbe."""
    # Arrange
    email = SentEmailFactory()

    # Act & Assert — pas d'exception, et le statut d'origine est préservé
    _email_send_failure(MagicMock(), RuntimeError("boom"), "task-id", [email.id], {}, None)

    email.refresh_from_db()
    assert email.status == Email.Status.SENT


@pytest.mark.django_db
def test_failure_handler_does_not_raise_when_args_are_empty():
    # Arrange — tâche appelée sans argument positionnel
    # Act & Assert — pas d'IndexError
    _email_send_failure(MagicMock(), RuntimeError("boom"), "task-id", [], {}, None)


@pytest.mark.django_db
def test_failure_handler_reads_email_id_from_kwargs():
    # Arrange — tâche appelée en kwargs plutôt qu'en args
    email = SendingEmailFactory()

    # Act
    _email_send_failure(MagicMock(), RuntimeError("boom"), "task-id", [], {"email_id": email.id}, None)

    # Assert
    email.refresh_from_db()
    assert email.status == Email.Status.FAILED


@pytest.mark.django_db
def test_failure_handler_does_not_touch_other_emails():
    # Arrange
    target = SendingEmailFactory()
    untouched = EmailFactory(status=Email.Status.READY)

    # Act
    _email_send_failure(MagicMock(), RuntimeError("boom"), "task-id", [target.id], {}, None)

    # Assert
    untouched.refresh_from_db()
    assert untouched.status == Email.Status.READY
