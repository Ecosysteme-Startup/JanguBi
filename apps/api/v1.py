"""Socle des APIs de la V1 : format d'erreur unifié (SRS §7).

``{"error": {"code": "...", "message": "...", "details": {...}}}``

Appliqué uniquement aux vues qui héritent de ``V1ApiMixin`` : les apps
existantes gardent leur format jusqu'à leur adaptation (pas de rupture front).
"""

from typing import Any

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.serializers import as_serializer_error
from rest_framework.views import exception_handler

from apps.core.exceptions import ApplicationError

_DRF_CODES = {
    exceptions.ValidationError: "validation_error",
    exceptions.NotAuthenticated: "not_authenticated",
    exceptions.AuthenticationFailed: "authentication_failed",
    exceptions.PermissionDenied: "permission_denied",
    exceptions.NotFound: "not_found",
    exceptions.MethodNotAllowed: "method_not_allowed",
    exceptions.Throttled: "throttled",
    exceptions.ParseError: "parse_error",
    exceptions.UnsupportedMediaType: "unsupported_media_type",
}


def error_body(*, code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def v1_exception_handler(exc: Exception, ctx: dict[str, Any]) -> Response | None:
    if isinstance(exc, ApplicationError):
        return Response(
            error_body(code=exc.code, message=exc.message, details=exc.extra), status=exc.status_code
        )
    if isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(as_serializer_error(exc))
    elif isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied()

    response = exception_handler(exc, ctx)
    if response is None or not isinstance(exc, exceptions.APIException):
        return response

    code = next((c for cls, c in _DRF_CODES.items() if isinstance(exc, cls)), exc.default_code)
    specific = exc.get_codes()
    if isinstance(specific, str) and specific != exc.default_code:
        code = specific  # ex. PermissionDenied(code="mfa_required")
    if isinstance(exc, exceptions.ValidationError):
        message, details = "Les données envoyées sont invalides.", response.data
    else:
        message, details = str(exc.detail), {}
    response.data = error_body(code=code, message=message, details=details)
    return response


class V1ApiMixin:
    """À placer en premier dans les bases des vues V1."""

    def get_exception_handler(self):  # noqa: D102 - API DRF
        return v1_exception_handler

