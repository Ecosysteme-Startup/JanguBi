class ApplicationError(Exception):
    """Erreur métier. ``code`` et ``status_code`` servent au format d'erreur V1
    (SRS §7 : ``{"error": {"code", "message", "details"}}``)."""

    code = "application_error"
    status_code = 400

    def __init__(self, message, extra=None, *, code=None):
        super().__init__(message)

        self.message = message
        self.extra = extra or {}
        if code is not None:
            self.code = code


class NotFoundError(ApplicationError):
    code = "not_found"
    status_code = 404


class PermissionDeniedError(ApplicationError):
    code = "permission_denied"
    status_code = 403


class ConflictError(ApplicationError):
    code = "conflict"
    status_code = 409


class OtpExpiredError(ApplicationError):
    pass


class OtpInvalidError(ApplicationError):
    pass


class OtpLockedError(ApplicationError):
    pass


class OtpRateLimitError(ApplicationError):
    pass


class TokenExpiredError(ApplicationError):
    pass


class TokenInvalidError(ApplicationError):
    pass
