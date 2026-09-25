import logging
from urllib.parse import parse_qs

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import UntypedToken

logger = logging.getLogger(__name__)

# Fermeture « non authentifié » (EF-AUTH-03) : le client rafraîchit son jeton et rouvre.
WS_CLOSE_UNAUTHENTICATED = 4401


class _InvalidToken(Exception):
    pass


def _legacy_user(token: str):
    from apps.users.models import BaseUser

    try:
        validated = UntypedToken(token)  # type: ignore[arg-type]  # stub SimpleJWT trop strict : UntypedToken accepte une str brute à l'exécution (validates signature + expiry)
        user = BaseUser.objects.get(id=validated["user_id"], is_active=True)
    except (InvalidToken, TokenError, KeyError, BaseUser.DoesNotExist) as exc:
        raise _InvalidToken from exc
    # Même règle que JwtKeyEnforcingJWTAuthentication côté REST : un token émis
    # avant rotate_jwt_key() (logout-all, changement de mot de passe) est rejeté.
    token_jwt_key = validated.payload.get("jwt_key")
    if token_jwt_key is None or str(token_jwt_key) != str(user.jwt_key):
        raise _InvalidToken
    return user


@database_sync_to_async
def _get_user_from_token(token: str):
    """Utilisateur du jeton (Keycloak, ou ancien JWT pendant la transition). Lève _InvalidToken."""
    from apps.authentication.keycloak import KeycloakTokenError, authenticate_token, is_keycloak_token

    if settings.KEYCLOAK_ENABLED and is_keycloak_token(token):
        try:
            user, _identity = authenticate_token(token)
        except KeycloakTokenError as exc:
            raise _InvalidToken from exc
        return user
    if not settings.LEGACY_JWT_ENABLED:
        raise _InvalidToken
    try:
        return _legacy_user(token)
    except _InvalidToken:
        raise
    except Exception as exc:
        logger.exception("Unexpected error while authenticating WebSocket JWT")
        raise _InvalidToken from exc


@database_sync_to_async
def _get_user_from_ticket(ticket: str):
    from apps.authentication.ws_tickets import ws_ticket_consume

    return ws_ticket_consume(ticket=ticket)


class JwtAuthMiddleware:
    """
    Authentifie la socket par ``?ticket=<ticket>`` (recommandé : ticket à usage unique
    obtenu par ``POST /api/v1/me/ws-ticket/``) ou, pendant la transition, ``?token=<jwt>``.

    Sans ticket ni jeton : utilisateur anonyme (le consommateur décide). Ticket ou jeton
    invalide ou expiré : la connexion est fermée avec le code 4401.
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        params = parse_qs(scope.get("query_string", b"").decode())
        ticket = params.get("ticket", [None])[0]
        token = params.get("token", [None])[0]

        if ticket:
            user = await _get_user_from_ticket(ticket)
            if user is None:
                await _reject(receive, send)
                return None
            scope["user"] = user
            return await self.inner(scope, receive, send)
        if not token:
            scope["user"] = AnonymousUser()
            return await self.inner(scope, receive, send)
        try:
            scope["user"] = await _get_user_from_token(token)
        except _InvalidToken:
            await _reject(receive, send)
            return None
        return await self.inner(scope, receive, send)


async def _reject(receive, send) -> None:
    message = await receive()
    if message.get("type") == "websocket.connect":
        await send({"type": "websocket.close", "code": WS_CLOSE_UNAUTHENTICATED})


def JwtAuthMiddlewareStack(inner):
    return JwtAuthMiddleware(AuthMiddlewareStack(inner))
