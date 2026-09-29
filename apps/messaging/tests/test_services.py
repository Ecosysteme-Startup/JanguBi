"""
Service-layer tests for apps/messaging.

Strategy:
- Every service function has a happy-path test and a test for each ApplicationError branch.
- transaction.on_commit callbacks (WebSocket fanout, task dispatch) are suppressed by
  patching Django's transaction.on_commit to call the callback immediately, then patching
  the actual side-effect (channel layer / celery task) so nothing hits the network.
- The channel layer helpers are patched at the services module level.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.core.exceptions import ApplicationError
from apps.files.tests.factories import FileFactory
from apps.messaging.models import (
    Message,
    MessageBlock,
    MessageReaction,
    Notification,
)
from apps.messaging.services import (
    block_user,
    conversation_accept_cgu,
    conversation_archive,
    conversation_delete,
    conversation_export_generate,
    conversation_export_request,
    conversation_get_or_create,
    conversation_purge_messages,
    message_delete,
    message_mark_read,
    message_react,
    message_send,
    message_unreact,
    notification_mark_read,
    notification_send,
    unblock_user,
)
from apps.users.tests.factories import BaseUserFactory

from .factories import (
    ConversationFactory,
    MessageBlockFactory,
    MessageFactory,
    MessageReactionFactory,
    NotificationFactory,
    reachable_priest,
)

# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------

_ON_COMMIT = "django.db.transaction.on_commit"
_FANOUT_WS = "apps.messaging.services._fanout_ws"
_FANOUT_NOTIF = "apps.messaging.services._fanout_notification"
_CACHE = "apps.messaging.services.cache"


# ---------------------------------------------------------------------------
# Conversation services
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_conversation_get_or_create_creates_new():
    # Arrange — le destinataire doit être un prêtre éligible (capacité messagerie.recevoir_fideles, disponibilité ouverte).
    fidele = BaseUserFactory()
    priest = BaseUserFactory()
    reachable_priest(priest)

    # Act
    conversation, created = conversation_get_or_create(fidele=fidele, priest=priest)

    # Assert
    assert created is True
    assert conversation.id is not None
    participant_ids = {conversation.participant_a_id, conversation.participant_b_id}
    assert fidele.id in participant_ids
    assert priest.id in participant_ids


@pytest.mark.django_db
def test_conversation_get_or_create_returns_existing():
    # Arrange
    existing = ConversationFactory()
    a = existing.participant_a
    b = existing.participant_b
    reachable_priest(b)

    # Act
    conversation, created = conversation_get_or_create(fidele=a, priest=b)

    # Assert
    assert created is False
    assert conversation.id == existing.id


@pytest.mark.django_db
def test_conversation_get_or_create_rejected_for_non_clergy_recipient():
    # Un fidèle ne peut pas ouvrir une conversation avec un autre fidèle : seul un
    # titulaire de messagerie.recevoir_fideles est joignable (EF-PRE-01).
    fidele = BaseUserFactory()
    other = BaseUserFactory()  # aucune nomination

    with pytest.raises(ApplicationError, match="pas joignable"):
        conversation_get_or_create(fidele=fidele, priest=other)


@pytest.mark.django_db
def test_conversation_get_or_create_rejected_when_priest_not_accepting():
    # Un prêtre joignable qui ne prend pas de nouveaux échanges (EF-PRE-07).
    from apps.messaging.models import MessagingAvailability

    fidele = BaseUserFactory()
    priest = BaseUserFactory()
    reachable_priest(priest, accepts=False)
    assert not MessagingAvailability.objects.get(user=priest).accepts_new_conversations

    with pytest.raises(ApplicationError, match="nouveaux échanges"):
        conversation_get_or_create(fidele=fidele, priest=priest)


@pytest.mark.django_db
def test_conversation_accept_cgu_participant_a_success():
    # Arrange
    conv = ConversationFactory(cgu_accepted_by_a=None)

    # Act
    updated = conversation_accept_cgu(conversation=conv, user=conv.participant_a)

    # Assert
    assert updated.cgu_accepted_by_a is not None


@pytest.mark.django_db
def test_conversation_accept_cgu_participant_b_success():
    # Arrange
    conv = ConversationFactory(cgu_accepted_by_b=None)

    # Act
    updated = conversation_accept_cgu(conversation=conv, user=conv.participant_b)

    # Assert
    assert updated.cgu_accepted_by_b is not None


@pytest.mark.django_db
def test_conversation_accept_cgu_raises_when_already_accepted_by_a():
    # Arrange
    conv = ConversationFactory(cgu_accepted_by_a=timezone.now())

    # Act & Assert
    with pytest.raises(ApplicationError, match="CGU"):
        conversation_accept_cgu(conversation=conv, user=conv.participant_a)


@pytest.mark.django_db
def test_conversation_accept_cgu_raises_when_already_accepted_by_b():
    # Arrange
    conv = ConversationFactory(cgu_accepted_by_b=timezone.now())

    # Act & Assert
    with pytest.raises(ApplicationError, match="CGU"):
        conversation_accept_cgu(conversation=conv, user=conv.participant_b)


@pytest.mark.django_db
def test_conversation_archive_sets_is_archived():
    # Arrange
    conv = ConversationFactory(is_archived=False)

    # Act
    updated = conversation_archive(conversation=conv, user=conv.participant_a)

    # Assert
    assert updated.is_archived is True
    conv.refresh_from_db()
    assert conv.is_archived is True


@pytest.mark.django_db
def test_conversation_delete_soft_deletes_messages_and_schedules_purge():
    # Arrange
    conv = ConversationFactory(
        cgu_accepted_by_a=timezone.now(),
        cgu_accepted_by_b=timezone.now(),
    )
    MessageFactory(conversation=conv, sender=conv.participant_a)
    MessageFactory(conversation=conv, sender=conv.participant_b)

    # Act — suppress on_commit side-effects
    with patch(_ON_COMMIT, lambda fn: None):
        conversation_delete(conversation=conv, user=conv.participant_a)

    # Assert — all messages soft-deleted
    messages = Message.objects.filter(conversation=conv)
    assert messages.filter(deleted_at__isnull=False).count() == 2
    # Purge scheduled
    conv.refresh_from_db()
    assert conv.scheduled_purge_at is not None


# ---------------------------------------------------------------------------
# Message services
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_message_send_success():
    # Arrange
    conv = ConversationFactory(
        cgu_accepted_by_a=timezone.now(),
        cgu_accepted_by_b=timezone.now(),
    )
    sender = conv.participant_a
    mock_cache = MagicMock()
    mock_cache.get_or_set.return_value = 0

    # Act
    with patch(_CACHE, mock_cache):
        with patch(_ON_COMMIT, lambda fn: fn()):
            with patch(_FANOUT_WS):
                message = message_send(
                    conversation=conv,
                    sender=sender,
                    content="Hello world",
                )

    # Assert
    assert message.id is not None
    assert message.content == "Hello world"
    assert message.sender == sender
    assert message.conversation == conv


@pytest.mark.django_db
def test_message_send_raises_when_blocked():
    # Arrange
    conv = ConversationFactory(
        cgu_accepted_by_a=timezone.now(),
        cgu_accepted_by_b=timezone.now(),
    )
    sender = conv.participant_a
    receiver = conv.participant_b
    MessageBlockFactory(blocker=sender, blocked=receiver)
    mock_cache = MagicMock()
    mock_cache.get_or_set.return_value = 0

    # Act & Assert
    with patch(_CACHE, mock_cache):
        with pytest.raises(ApplicationError, match="bloqu"):
            message_send(conversation=conv, sender=sender, content="Hi")


@pytest.mark.django_db
def test_message_send_raises_when_cgu_not_accepted_by_sender():
    # Arrange
    conv = ConversationFactory(cgu_accepted_by_a=None, cgu_accepted_by_b=None)
    sender = conv.participant_a

    # Act & Assert
    with pytest.raises(ApplicationError, match="CGU"):
        message_send(conversation=conv, sender=sender, content="Hi")


@pytest.mark.django_db
def test_message_send_raises_when_rate_limit_exceeded():
    # Arrange
    conv = ConversationFactory(
        cgu_accepted_by_a=timezone.now(),
        cgu_accepted_by_b=timezone.now(),
    )
    sender = conv.participant_a
    mock_cache = MagicMock()
    mock_cache.get_or_set.return_value = 9999  # well above any configured limit

    with patch(_CACHE, mock_cache):
        with pytest.raises(ApplicationError, match="Limite"):
            message_send(conversation=conv, sender=sender, content="Hi")


@pytest.mark.django_db
def test_message_send_idempotent_with_same_client_message_id():
    # Arrange
    conv = ConversationFactory(
        cgu_accepted_by_a=timezone.now(),
        cgu_accepted_by_b=timezone.now(),
    )
    sender = conv.participant_a
    mock_cache = MagicMock()
    mock_cache.get_or_set.return_value = 0
    client_id = str(uuid.uuid4())

    with patch(_CACHE, mock_cache):
        with patch(_ON_COMMIT, lambda fn: fn()):
            with patch(_FANOUT_WS):
                first = message_send(
                    conversation=conv,
                    sender=sender,
                    content="Hello",
                    client_message_id=client_id,
                )
                second = message_send(
                    conversation=conv,
                    sender=sender,
                    content="Hello",
                    client_message_id=client_id,
                )

    # Assert — same DB row returned on duplicate submission
    assert first.id == second.id
    assert Message.objects.filter(client_message_id=client_id).count() == 1


@pytest.mark.django_db
def test_message_mark_read_marks_counterpart_messages():
    # Arrange
    conv = ConversationFactory(
        cgu_accepted_by_a=timezone.now(),
        cgu_accepted_by_b=timezone.now(),
    )
    sender = conv.participant_a
    reader = conv.participant_b
    MessageFactory(conversation=conv, sender=sender, read_at=None)
    MessageFactory(conversation=conv, sender=sender, read_at=None)

    with patch(_ON_COMMIT, lambda fn: fn()):
        with patch(_FANOUT_WS):
            # Act
            updated_count = message_mark_read(conversation=conv, reader=reader)

    # Assert
    assert updated_count == 2
    assert Message.objects.filter(conversation=conv, read_at__isnull=False).count() == 2


@pytest.mark.django_db
def test_message_mark_read_skips_own_messages():
    # Arrange
    conv = ConversationFactory(
        cgu_accepted_by_a=timezone.now(),
        cgu_accepted_by_b=timezone.now(),
    )
    sender = conv.participant_a
    MessageFactory(conversation=conv, sender=sender, read_at=None)

    # Act — sender reads own messages
    updated_count = message_mark_read(conversation=conv, reader=sender)

    # Assert — own messages must not be marked
    assert updated_count == 0


@pytest.mark.django_db
def test_message_delete_success():
    # Arrange
    msg = MessageFactory()
    sender = msg.sender

    # Act
    deleted = message_delete(message=msg, user=sender)

    # Assert
    assert deleted.is_deleted is True
    assert deleted.content == ""
    msg.refresh_from_db()
    assert msg.deleted_at is not None


@pytest.mark.django_db
def test_message_delete_raises_when_not_sender():
    # Arrange
    msg = MessageFactory()
    other_user = BaseUserFactory()

    # Act & Assert
    with pytest.raises(ApplicationError, match="propres messages"):
        message_delete(message=msg, user=other_user)


@pytest.mark.django_db
def test_message_delete_raises_when_already_deleted():
    # Arrange
    msg = MessageFactory(deleted_at=timezone.now(), content="")

    # Act & Assert
    with pytest.raises(ApplicationError, match="déjà supprimé"):
        message_delete(message=msg, user=msg.sender)


@pytest.mark.django_db
def test_message_react_creates_reaction():
    # Arrange
    msg = MessageFactory()
    user = BaseUserFactory()

    # Act
    reaction = message_react(message=msg, user=user, emoji="like")

    # Assert
    assert reaction.id is not None
    assert reaction.emoji == "like"
    assert MessageReaction.objects.filter(message=msg, user=user, emoji="like").exists()


@pytest.mark.django_db
def test_message_react_is_idempotent():
    # Arrange
    msg = MessageFactory()
    user = BaseUserFactory()

    # Act
    r1 = message_react(message=msg, user=user, emoji="like")
    r2 = message_react(message=msg, user=user, emoji="like")

    # Assert — get_or_create returns the same object
    assert r1.id == r2.id
    assert MessageReaction.objects.filter(message=msg, user=user, emoji="like").count() == 1


@pytest.mark.django_db
def test_message_unreact_removes_reaction():
    # Arrange
    reaction = MessageReactionFactory(emoji="like")
    msg = reaction.message
    user = reaction.user

    # Act
    message_unreact(message=msg, user=user, emoji="like")

    # Assert
    assert not MessageReaction.objects.filter(message=msg, user=user, emoji="like").exists()


@pytest.mark.django_db
def test_message_unreact_silent_when_no_reaction_exists():
    # Arrange — no reaction created
    msg = MessageFactory()
    user = BaseUserFactory()

    # Act — must not raise
    message_unreact(message=msg, user=user, emoji="love")

    # Assert
    assert not MessageReaction.objects.filter(message=msg, user=user, emoji="love").exists()


# ---------------------------------------------------------------------------
# Block services
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_block_user_success():
    # Arrange
    blocker = BaseUserFactory()
    blocked = BaseUserFactory()

    # Act
    block = block_user(blocker=blocker, blocked=blocked)

    # Assert
    assert block.id is not None
    assert MessageBlock.objects.filter(blocker=blocker, blocked=blocked).exists()


@pytest.mark.django_db
def test_block_user_raises_when_blocking_self():
    # Arrange
    user = BaseUserFactory()

    # Act & Assert
    with pytest.raises(ApplicationError, match="soi-même"):
        block_user(blocker=user, blocked=user)


@pytest.mark.django_db
def test_block_user_raises_when_already_blocked():
    # Arrange
    block = MessageBlockFactory()

    # Act & Assert
    with pytest.raises(ApplicationError, match="déjà bloqué"):
        block_user(blocker=block.blocker, blocked=block.blocked)


@pytest.mark.django_db
def test_unblock_user_success():
    # Arrange
    block = MessageBlockFactory()
    blocker = block.blocker
    blocked = block.blocked

    # Act
    unblock_user(blocker=blocker, blocked=blocked)

    # Assert
    assert not MessageBlock.objects.filter(blocker=blocker, blocked=blocked).exists()


@pytest.mark.django_db
def test_unblock_user_raises_when_no_block_exists():
    # Arrange
    blocker = BaseUserFactory()
    blocked = BaseUserFactory()

    # Act & Assert
    with pytest.raises(ApplicationError, match="Aucun blocage"):
        unblock_user(blocker=blocker, blocked=blocked)


# ---------------------------------------------------------------------------
# Export service
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_conversation_export_request_creates_export_record():
    # Arrange
    conv = ConversationFactory()
    user = conv.participant_a

    # Act — suppress on_commit so the Celery task is never dispatched
    with patch(_ON_COMMIT, lambda fn: None):
        export = conversation_export_request(conversation=conv, user=user)

    # Assert
    assert export.id is not None
    assert export.conversation == conv
    assert export.requested_by == user
    assert export.completed_at is None


# ---------------------------------------------------------------------------
# Notification services
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_notification_send_creates_notification_record():
    # Arrange
    user = BaseUserFactory()

    # Act
    with patch(_ON_COMMIT, lambda fn: fn()):
        with patch(_FANOUT_NOTIF):
            notif = notification_send(
                user=user,
                event_type="message.received",
                payload={"text": "hello"},
            )

    # Assert
    assert notif.id is not None
    assert notif.event_type == "message.received"
    assert notif.payload == {"text": "hello"}
    assert Notification.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_notification_mark_read_success():
    # Arrange
    notif = NotificationFactory(is_read=False)
    user = notif.user

    # Act
    updated = notification_mark_read(notification=notif, user=user)

    # Assert
    assert updated.is_read is True
    assert updated.read_at is not None


@pytest.mark.django_db
def test_notification_mark_read_idempotent_when_already_read():
    # Arrange
    read_at = timezone.now()
    notif = NotificationFactory(is_read=True, read_at=read_at)
    user = notif.user

    # Act
    result = notification_mark_read(notification=notif, user=user)

    # Assert — returned as-is without error or timestamp change
    assert result.is_read is True
    assert result.read_at == read_at


@pytest.mark.django_db
def test_notification_mark_read_raises_when_wrong_user():
    # Arrange
    notif = NotificationFactory(is_read=False)
    other_user = BaseUserFactory()

    # Act & Assert
    with pytest.raises(ApplicationError, match="refus"):
        notification_mark_read(notification=notif, user=other_user)


# ---------------------------------------------------------------------------
# conversation_purge_messages
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_conversation_purge_messages_wipes_content():
    # Arrange
    conv = ConversationFactory()
    MessageFactory(conversation=conv, sender=conv.participant_a, content="Secret message")
    MessageFactory(conversation=conv, sender=conv.participant_b, content="Another secret")

    # Act
    conversation_purge_messages(conversation=conv)

    # Assert — content wiped to empty string and deleted_at set
    from apps.messaging.models import Message

    messages = Message.objects.filter(conversation=conv)
    for msg in messages:
        assert msg.content == ""
        assert msg.deleted_at is not None


@pytest.mark.django_db
def test_conversation_purge_messages_clears_scheduled_purge_at():
    # Arrange
    from django.utils import timezone as tz

    conv = ConversationFactory(scheduled_purge_at=tz.now())

    # Act
    conversation_purge_messages(conversation=conv)

    # Assert
    conv.refresh_from_db()
    assert conv.scheduled_purge_at is None


@pytest.mark.django_db
def test_conversation_purge_messages_does_not_affect_other_conversations():
    # Arrange
    conv_target = ConversationFactory()
    conv_other = ConversationFactory()
    MessageFactory(conversation=conv_target, sender=conv_target.participant_a, content="To be wiped")
    msg_other = MessageFactory(conversation=conv_other, sender=conv_other.participant_a, content="Keep this")

    # Act
    conversation_purge_messages(conversation=conv_target)

    # Assert — other conversation's messages untouched
    msg_other.refresh_from_db()
    assert msg_other.content == "Keep this"
    assert msg_other.deleted_at is None


# ---------------------------------------------------------------------------
# conversation_export_generate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_conversation_export_generate_sets_completed_at():
    # Arrange
    from apps.messaging.models import ConversationExport

    conv = ConversationFactory()
    export = ConversationExport.objects.create(conversation=conv)

    # Return a REAL File row from File.objects.create so the FK assignment +
    # export.save() are valid; stub only the storage write (file.save) so the
    # test never touches the real filesystem/S3.
    def _make_real_file(**kwargs):
        file_obj = FileFactory(**kwargs)
        file_obj.file.save = MagicMock()
        return file_obj

    # Act — patch PDF generation and storage so tests need no real filesystem
    with patch("apps.messaging.services._generate_export_pdf", return_value=b"%PDF-stub"):
        with patch("apps.messaging.services.File") as MockFile:
            MockFile.objects.create.side_effect = _make_real_file
            result = conversation_export_generate(export_id=str(export.id))

    # Assert — export record marks completion
    assert result.completed_at is not None


@pytest.mark.django_db
def test_conversation_export_generate_without_export_id_creates_new_export():
    # Arrange
    from apps.messaging.models import ConversationExport

    conv = ConversationFactory()

    # Return a REAL File row from File.objects.create so the FK assignment +
    # export.save() are valid; stub only the storage write (file.save) so the
    # test never touches the real filesystem/S3.
    def _make_real_file(**kwargs):
        file_obj = FileFactory(**kwargs)
        file_obj.file.save = MagicMock()
        return file_obj

    # Act — patch file operations to avoid real storage
    with patch("apps.messaging.services._generate_export_pdf", return_value=b"%PDF-stub"):
        with patch("apps.messaging.services.File") as MockFile:
            MockFile.objects.create.side_effect = _make_real_file
            result = conversation_export_generate(conversation_id=str(conv.id))

    # Assert — a new export record was created and completed
    assert ConversationExport.objects.filter(conversation=conv).count() >= 1
    assert result.completed_at is not None
