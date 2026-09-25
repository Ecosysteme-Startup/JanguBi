from typing import TYPE_CHECKING, Sequence, Type

from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission, IsAuthenticated

from apps.authentication.keycloak import KeycloakJWTAuthentication

if TYPE_CHECKING:
    # This is going to be resolved in the stub library
    # https://github.com/typeddjango/djangorestframework-stubs/
    from rest_framework.permissions import _PermissionClass

    PermissionClassesType = Sequence[_PermissionClass]
else:
    PermissionClassesType = Sequence[Type[BasePermission]]


class ApiAuthMixin:
    # Keycloak seul (ADR-004) : plus de session ni d'ancien JWT sur l'API.
    authentication_classes: Sequence[Type[BaseAuthentication]] = [KeycloakJWTAuthentication]
    permission_classes: PermissionClassesType = (IsAuthenticated,)
