#!/bin/sh
# Serveur HTTP de l'API : ASGI (Channels, WebSocket, SSE) via Daphne.
set -e
echo "--> daphne (ASGI)"
exec daphne -b 0.0.0.0 -p "${PORT:-8000}" --proxy-headers config.asgi:application
