from rest_framework.permissions import BasePermission

from apps.messaging.models import (
    Conversation,
    Message,
    MessageBlock,
    MessagingCguAcceptance,
)


class IsParticipant(BasePermission):
    """Request user is participant_a or participant_b of the conversation."""

    message = "Vous n'êtes pas participant de cette conversation."

    def has_object_permission(self, request, view, obj) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if isinstance(obj, Conversation):
            return (
                obj.participant_a_id == request.user.id
                or obj.participant_b_id == request.user.id
            )
        return False


class HasAcceptedMessagingCgu(BasePermission):
    """
    Request user has accepted the messaging CGU — globally (MessagingCguAcceptance,
    une fois pour toutes) OR for this specific conversation (flags historiques).
    """

    message = "Vous devez accepter les CGU de messagerie pour accéder aux messages."

    def has_object_permission(self, request, view, obj) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if isinstance(obj, Conversation):
            if MessagingCguAcceptance.objects.filter(user=request.user).exists():
                return True
            if obj.participant_a_id == request.user.id:
                return obj.cgu_accepted_by_a is not None
            return obj.cgu_accepted_by_b is not None
        return False


class IsMessageSender(BasePermission):
    """Request user is the sender of the message."""

    message = "Vous ne pouvez agir que sur vos propres messages."

    def has_object_permission(self, request, view, obj) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if isinstance(obj, Message):
            return obj.sender_id == request.user.id
        return False


class IsBlockOwner(BasePermission):
    """Request user is the blocker."""

    message = "Vous ne pouvez gérer que vos propres blocages."

    def has_object_permission(self, request, view, obj) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        if isinstance(obj, MessageBlock):
            return obj.blocker_id == request.user.id
        return False
