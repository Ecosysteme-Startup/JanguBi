from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed


class JwtKeyEnforcingJWTAuthentication(JWTAuthentication):
    """
    JWTAuthentication qui compare la claim `jwt_key` du token à la valeur courante
    de l'utilisateur (BaseUser.jwt_key, UUID rotatif).

    Sans cette vérification, rotate_jwt_key() (logout-all, changement de mot de
    passe) n'invalidait AUCUN access token : SimpleJWT signe avec SECRET_KEY et la
    claim injectée par CustomTokenObtainPairSerializer restait décorative.

    Les tokens issus d'un refresh conservent la claim (SimpleJWT copie les claims
    custom du refresh vers l'access) : un refresh antérieur à la rotation produit
    donc un access immédiatement rejeté ici.
    """

    def authenticate(self, request):
        # Après la bascule Keycloak (LEGACY_JWT_ENABLED=false), les anciens jetons ne valent plus rien.
        if not settings.LEGACY_JWT_ENABLED:
            return None
        return super().authenticate(request)

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        token_jwt_key = validated_token.payload.get("jwt_key")
        if token_jwt_key is None or str(token_jwt_key) != str(user.jwt_key):
            raise AuthenticationFailed("Token révoqué.", code="token_revoked")
        return user
