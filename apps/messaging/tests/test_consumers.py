import asyncio

from apps.messaging.consumers import ConversationConsumer


def _frames(handler: str, event: dict) -> list[dict]:
    consumer = ConversationConsumer()
    sent: list[dict] = []

    async def send_json(content, close=False):
        sent.append(content)

    consumer.send_json = send_json  # type: ignore[method-assign]
    asyncio.run(getattr(consumer, handler)(event))
    return sent


def test_conv_read_frame_keeps_client_type():
    # Arrange
    event = {"type": "conv_read", "user_id": "u1", "message_ids": ["m1"]}

    # Act
    frames = _frames("conv_read", event)

    # Assert : la clé de dispatch Channels n'écrase pas le type de la trame.
    assert frames == [{"type": "message.read", "user_id": "u1", "message_ids": ["m1"]}]


def test_conv_typing_frame_keeps_client_type():
    frames = _frames("conv_typing", {"type": "conv_typing", "user_id": "u1", "is_typing": True})

    assert frames == [{"type": "typing", "user_id": "u1", "is_typing": True}]
