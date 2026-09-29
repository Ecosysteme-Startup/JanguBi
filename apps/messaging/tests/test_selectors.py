"""
Selector-layer tests for apps/messaging.

Strategy:
- Each selector is tested for the happy path (correct data returned) and each
  meaningful filter variation.
- No DB writes happen inside selectors; factories set up the state.
- conversation_get returns None (not an exception) when the conversation is not
  found or the requesting user is not a participant — this matches the selector
  implementation exactly.
"""

import uuid
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.messaging.models import Message
from apps.messaging.selectors import (
    block_list,
    conversation_get,
    conversation_list,
    export_list,
    message_list,
    notification_list,
    unread_count,
)
from apps.users.tests.factories import BaseUserFactory

from .factories import (
    ConversationFactory,
    MessageBlockFactory,
    MessageFactory,
    NotificationFactory,
)

# ---------------------------------------------------------------------------
# conversation_list
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_conversation_list_returns_only_user_conversations():
    # Arrange
    user = BaseUserFactory()
    other_a = BaseUserFactory()
    other_b = BaseUserFactory()

    conv_as_a = ConversationFactory(participant_a=user, participant_b=other_a)
    conv_as_b = ConversationFactory(participant_a=user, participant_b=other_b)
    # Conversation that does not involve the user at all
    other_c = BaseUserFactory()
    ConversationFactory(participant_a=other_a, participant_b=other_c)

    # Act
    qs = conversation_list(user=user)
    result_ids = set(qs.values_list("id", flat=True))

    # Assert — only the two conversations that involve the user
    assert len(result_ids) == 2
    assert conv_as_a.id in result_ids
    assert conv_as_b.id in result_ids


@pytest.mark.django_db
def test_conversation_list_annotates_unread_count():
    # Arrange
    user = BaseUserFactory()
    other = BaseUserFactory()
    conv = ConversationFactory(participant_a=user, participant_b=other)

    # Two unread messages from the other participant
    MessageFactory(conversation=conv, sender=other, read_at=None)
    MessageFactory(conversation=conv, sender=other, read_at=None)
    # Already read — must not count
    MessageFactory(conversation=conv, sender=other, read_at=timezone.now())
    # Own message — must NOT be counted
    MessageFactory(conversation=conv, sender=user, read_at=None)

    # Act
    result = conversation_list(user=user)
    conv_row = result.get(pk=conv.pk)

    # Assert
    assert conv_row.unread_count == 2


@pytest.mark.django_db
def test_conversation_list_ordered_by_last_message_at_descending():
    # Arrange
    user = BaseUserFactory()
    other_a = BaseUserFactory()
    other_b = BaseUserFactory()

    old_time = timezone.now().replace(year=2020)
    new_time = timezone.now()

    conv_old = ConversationFactory(
        participant_a=user, participant_b=other_a, last_message_at=old_time
    )
    conv_new = ConversationFactory(
        participant_a=user, participant_b=other_b, last_message_at=new_time
    )

    # Act
    qs = list(conversation_list(user=user))

    # Assert — newest first
    assert qs[0].id == conv_new.id
    assert qs[1].id == conv_old.id


# ---------------------------------------------------------------------------
# conversation_get
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_conversation_get_returns_conversation_for_participant_a():
    # Arrange
    conv = ConversationFactory()
    user = conv.participant_a

    # Act
    result = conversation_get(conversation_id=conv.id, user=user)

    # Assert
    assert result is not None
    assert result.id == conv.id


@pytest.mark.django_db
def test_conversation_get_returns_conversation_for_participant_b():
    # Arrange
    conv = ConversationFactory()
    user = conv.participant_b

    # Act
    result = conversation_get(conversation_id=conv.id, user=user)

    # Assert
    assert result is not None
    assert result.id == conv.id


@pytest.mark.django_db
def test_conversation_get_returns_none_for_non_participant():
    # Arrange
    conv = ConversationFactory()
    outsider = BaseUserFactory()

    # Act
    result = conversation_get(conversation_id=conv.id, user=outsider)

    # Assert
    assert result is None


@pytest.mark.django_db
def test_conversation_get_returns_none_when_not_found():
    # Arrange
    user = BaseUserFactory()
    nonexistent_id = uuid.uuid4()

    # Act
    result = conversation_get(conversation_id=nonexistent_id, user=user)

    # Assert
    assert result is None


# ---------------------------------------------------------------------------
# message_list
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_message_list_returns_messages_for_conversation():
    # Arrange
    conv = ConversationFactory()
    msg1 = MessageFactory(conversation=conv)
    msg2 = MessageFactory(conversation=conv)
    # Message in another conversation — must not appear
    MessageFactory()

    # Act
    result = list(message_list(conversation=conv))

    # Assert
    result_ids = {m.id for m in result}
    assert msg1.id in result_ids
    assert msg2.id in result_ids
    assert len(result_ids) == 2


@pytest.mark.django_db
def test_message_list_respects_limit():
    # Arrange
    conv = ConversationFactory()
    for _ in range(10):
        MessageFactory(conversation=conv)

    # Act
    result = list(message_list(conversation=conv, limit=3))

    # Assert
    assert len(result) == 3


@pytest.mark.django_db
def test_message_list_ordered_newest_first():
    # Arrange
    conv = ConversationFactory()
    MessageFactory(conversation=conv)
    MessageFactory(conversation=conv)

    # Act
    result = list(message_list(conversation=conv, limit=10))

    # Assert — created_at descending
    created_ats = [m.created_at for m in result]
    assert created_ats == sorted(created_ats, reverse=True)


@pytest.mark.django_db
def test_message_list_cursor_pagination_with_before_id():
    # Arrange — give each message a strictly increasing created_at so the
    # cursor (which filters on created_at__lt, matching order_by("-created_at"))
    # has an unambiguous ordering to page against.
    conv = ConversationFactory()
    base = timezone.now()
    messages = []
    for i in range(5):
        msg = MessageFactory(conversation=conv)
        Message.objects.filter(pk=msg.pk).update(
            created_at=base + timezone.timedelta(seconds=i)
        )
        msg.refresh_from_db()
        messages.append(msg)

    # Newest message is the pivot; the 4 older ones all precede it.
    pivot = messages[-1]

    # Act — only messages created before the pivot should be returned
    result = list(message_list(conversation=conv, before_id=pivot.id, limit=100))

    # Assert — the other 4 messages all have created_at < pivot.created_at
    assert len(result) == 4
    for msg in result:
        assert msg.created_at < pivot.created_at


# ---------------------------------------------------------------------------
# unread_count
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_unread_count_counts_only_unread_from_other_participant():
    # Arrange
    conv = ConversationFactory()
    reader = conv.participant_b
    sender = conv.participant_a

    MessageFactory(conversation=conv, sender=sender, read_at=None)
    MessageFactory(conversation=conv, sender=sender, read_at=None)
    # Already read — must not count
    MessageFactory(conversation=conv, sender=sender, read_at=timezone.now())
    # Own message — must not count
    MessageFactory(conversation=conv, sender=reader, read_at=None)

    # Act
    count = unread_count(conversation=conv, user=reader)

    # Assert
    assert count == 2


@pytest.mark.django_db
def test_unread_count_excludes_soft_deleted_messages():
    # Arrange
    conv = ConversationFactory()
    reader = conv.participant_b
    sender = conv.participant_a

    # Deleted message — must not count even if read_at is null
    MessageFactory(
        conversation=conv, sender=sender, read_at=None, deleted_at=timezone.now()
    )

    # Act
    count = unread_count(conversation=conv, user=reader)

    # Assert
    assert count == 0


@pytest.mark.django_db
def test_unread_count_returns_zero_when_no_messages():
    # Arrange
    conv = ConversationFactory()
    reader = conv.participant_b

    # Act
    count = unread_count(conversation=conv, user=reader)

    # Assert
    assert count == 0


# ---------------------------------------------------------------------------
# block_list
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_block_list_returns_only_blocks_owned_by_user():
    # Arrange
    user = BaseUserFactory()
    target1 = BaseUserFactory()
    target2 = BaseUserFactory()
    b1 = MessageBlockFactory(blocker=user, blocked=target1)
    b2 = MessageBlockFactory(blocker=user, blocked=target2)
    # Block belonging to a different blocker — must not appear
    other = BaseUserFactory()
    MessageBlockFactory(blocker=other, blocked=user)

    # Act
    result = block_list(user=user)

    # Assert
    result_ids = {b.id for b in result}
    assert b1.id in result_ids
    assert b2.id in result_ids
    assert result.count() == 2


@pytest.mark.django_db
def test_block_list_returns_empty_when_no_blocks():
    # Arrange
    user = BaseUserFactory()

    # Act
    result = block_list(user=user)

    # Assert
    assert result.count() == 0


# ---------------------------------------------------------------------------
# export_list
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_export_list_returns_exports_scoped_to_conversation():
    # Arrange
    from apps.messaging.services import conversation_export_request

    conv = ConversationFactory()
    user = conv.participant_a

    with patch("django.db.transaction.on_commit", lambda fn: None):
        export1 = conversation_export_request(conversation=conv, user=user)
        export2 = conversation_export_request(conversation=conv, user=user)

    # Export for a different conversation — must not appear
    other_conv = ConversationFactory()
    with patch("django.db.transaction.on_commit", lambda fn: None):
        conversation_export_request(
            conversation=other_conv, user=other_conv.participant_a
        )

    # Act
    result = export_list(conversation=conv)

    # Assert
    result_ids = {e.id for e in result}
    assert export1.id in result_ids
    assert export2.id in result_ids
    assert result.count() == 2


# ---------------------------------------------------------------------------
# notification_list
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_notification_list_returns_all_for_user():
    # Arrange
    user = BaseUserFactory()
    n1 = NotificationFactory(user=user, is_read=False)
    n2 = NotificationFactory(user=user, is_read=True)
    # Notification for another user — must not appear
    NotificationFactory()

    # Act
    result = notification_list(user=user)

    # Assert
    result_ids = {n.id for n in result}
    assert n1.id in result_ids
    assert n2.id in result_ids
    assert result.count() == 2


@pytest.mark.django_db
def test_notification_list_unread_only_filter():
    # Arrange
    user = BaseUserFactory()
    unread = NotificationFactory(user=user, is_read=False)
    read = NotificationFactory(user=user, is_read=True)

    # Act
    result = notification_list(user=user, unread_only=True)

    # Assert
    result_ids = {n.id for n in result}
    assert unread.id in result_ids
    assert read.id not in result_ids


@pytest.mark.django_db
def test_notification_list_ordered_newest_first():
    # Arrange
    user = BaseUserFactory()
    NotificationFactory(user=user)
    NotificationFactory(user=user)

    # Act
    result = list(notification_list(user=user))

    # Assert
    created_ats = [n.created_at for n in result]
    assert created_ats == sorted(created_ats, reverse=True)
