from django.conf import settings


def test_channel_layer_socket_timeout_exceeds_blocking_receive():
    # channels_redis attend jusqu'à 5 s (brpop) : un délai de socket inférieur ou égal coupe
    # chaque WebSocket (fermeture 1011). Recette du 26/09/2026, DEF-06.
    host = settings.CHANNEL_LAYERS["default"]["CONFIG"]["hosts"][0]
    assert isinstance(host, dict)
    assert host["socket_timeout"] > 5
