from urllib.parse import parse_qs

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser

# Fermeture « non authentifié » (EF-AUTH-03) : le client rafraîchit son jeton et rouvre.
WS_CLOSE_UNAUTHENTICATED = 4401


@database_sync_to_async
def _get_user_from_ticket(ticket: str):
    from apps.authentication.ws_tickets import ws_ticket_consume

    return ws_ticket_consume(ticket=ticket)


class JwtAuthMiddleware:
    """
    Authentifie la socket par ``?ticket=<ticket>`` : ticket à usage unique obtenu avec le
    jeton Keycloak par ``POST /api/v1/me/ws-ticket/`` (le jeton lui-même ne passe jamais
    dans l'URL, donc jamais dans les journaux). Sans ticket : utilisateur anonyme (le
    consommateur décide). Ticket invalide ou expiré : fermeture avec le code 4401.
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        params = parse_qs(scope.get("query_string", b"").decode())
        ticket = params.get("ticket", [None])[0]
        if not ticket:
            scope["user"] = AnonymousUser()
            return await self.inner(scope, receive, send)
        user = await _get_user_from_ticket(ticket)
        if user is None:
            await _reject(receive, send)
            return None
        scope["user"] = user
        return await self.inner(scope, receive, send)


async def _reject(receive, send) -> None:
    message = await receive()
    if message.get("type") == "websocket.connect":
        await send({"type": "websocket.close", "code": WS_CLOSE_UNAUTHENTICATED})


def JwtAuthMiddlewareStack(inner):
    return JwtAuthMiddleware(AuthMiddlewareStack(inner))
