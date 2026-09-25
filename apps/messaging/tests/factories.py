"""
factory_boy factories for apps/messaging tests.

Encryption is transparent at the model level (EncryptedTextField.get_prep_value),
so plain strings assigned to `content` are encrypted on save and decrypted on read
without any special handling required in factories.
"""

import factory
from factory.django import DjangoModelFactory

from apps.messaging.models import (
    Conversation,
    Message,
    MessageBlock,
    MessageReaction,
    Notification,
    PriestProfile,
)
from apps.users.tests.factories import BaseUserFactory


class PriestProfileFactory(DjangoModelFactory):
    """Prêtre joignable : profil historique + nomination de vicaire (messagerie.recevoir_fideles)."""

    user = factory.SubFactory(BaseUserFactory)
    accepts_pastoral_chat = True
    bio = factory.Sequence(lambda n: f"Bio du pretre {n}")
    ordination_year = 2000

    class Meta:
        model = PriestProfile

    @factory.post_generation
    def reachable(obj, create, extracted, **kwargs):  # noqa: N805 — convention factory_boy
        if not create or extracted is False:
            return
        from apps.hierarchy.tests.factories import make_node, nominate

        parish = make_node("paroisse", f"Paroisse de test {obj.user_id}", _test_diocese())
        nominate(obj.user, "vicaire_paroissial", parish)


def _test_diocese():
    from apps.hierarchy.models import Node
    from apps.hierarchy.tests.factories import make_node

    diocese = Node.objects.filter(code="MSG-TEST-DIO").first()
    if diocese is None:
        province = make_node("province", "Province de test (messagerie)", code="MSG-TEST-PROV")
        diocese = make_node("diocese", "Diocèse de test (messagerie)", province, code="MSG-TEST-DIO")
    return diocese


class ConversationFactory(DjangoModelFactory):
    """
    Creates a Conversation between two distinct users.
    Enforces participant_a.id < participant_b.id (UUID string comparison) at creation time.
    """

    participant_a = factory.SubFactory(BaseUserFactory)
    participant_b = factory.SubFactory(BaseUserFactory)

    class Meta:
        model = Conversation

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        a = kwargs.pop("participant_a")
        b = kwargs.pop("participant_b")
        # Enforce canonical ordering required by the model constraint
        if str(a.id) <= str(b.id):
            pa, pb = a, b
        else:
            pa, pb = b, a
        return model_class.objects.create(participant_a=pa, participant_b=pb, **kwargs)


class MessageFactory(DjangoModelFactory):
    conversation = factory.SubFactory(ConversationFactory)
    sender = factory.LazyAttribute(lambda o: o.conversation.participant_a)
    # Plain string — EncryptedTextField handles encryption transparently
    content = factory.Sequence(lambda n: f"Message content {n}")
    content_type = Message.ContentType.TEXT

    class Meta:
        model = Message


class MessageBlockFactory(DjangoModelFactory):
    blocker = factory.SubFactory(BaseUserFactory)
    blocked = factory.SubFactory(BaseUserFactory)

    class Meta:
        model = MessageBlock


class MessageReactionFactory(DjangoModelFactory):
    message = factory.SubFactory(MessageFactory)
    user = factory.SubFactory(BaseUserFactory)
    emoji = "like"

    class Meta:
        model = MessageReaction


class NotificationFactory(DjangoModelFactory):
    user = factory.SubFactory(BaseUserFactory)
    event_type = "test.event"
    payload = factory.LazyFunction(dict)
    is_read = False

    class Meta:
        model = Notification
