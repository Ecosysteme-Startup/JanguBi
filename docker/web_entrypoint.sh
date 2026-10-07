#!/bin/sh
# Serveur HTTP de l'API : ASGI (Channels, WebSocket, SSE) via Daphne.
set -e
echo "--> daphne (ASGI)"
# JB-API-005 : --server-name masque l'en-tête « Server: daphne/<version> » (empreinte technique).
exec daphne -b 0.0.0.0 -p "${PORT:-8000}" --proxy-headers --server-name JanguBi config.asgi:application
