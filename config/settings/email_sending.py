from apps.emails.enums import EmailSendingStrategy
from config.env import env, env_to_enum

# local | mailtrap
EMAIL_SENDING_STRATEGY = env_to_enum(EmailSendingStrategy, env("EMAIL_SENDING_STRATEGY", default="local"))

EMAIL_SENDING_FAILURE_TRIGGER = env.bool("EMAIL_SENDING_FAILURE_TRIGGER", default=False)
EMAIL_SENDING_FAILURE_RATE = env.float("EMAIL_SENDING_FAILURE_RATE", default=0.2)

if EMAIL_SENDING_STRATEGY == EmailSendingStrategy.LOCAL:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

if EMAIL_SENDING_STRATEGY == EmailSendingStrategy.MAILHOG:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    # Stratégie « mailhog » = SMTP local sans authentification ; en dev, le conteneur est Mailpit.
    EMAIL_HOST = env("MAILHOG_HOST", default="mailpit")
    EMAIL_PORT = env.int("MAILHOG_PORT", default=1025)
    EMAIL_USE_TLS = False
    EMAIL_USE_SSL = False

if EMAIL_SENDING_STRATEGY == EmailSendingStrategy.MAILTRAP:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = env("MAILTRAP_EMAIL_HOST")
    EMAIL_HOST_USER = env("MAILTRAP_EMAIL_HOST_USER")
    EMAIL_HOST_PASSWORD = env("MAILTRAP_EMAIL_HOST_PASSWORD")
    EMAIL_PORT = env.int("MAILTRAP_EMAIL_PORT", default=587)
    EMAIL_USE_TLS = True
    DEFAULT_FROM_EMAIL = env("EMAIL_FROM_ADDRESS", default="noreply@jangubi.kamalfils.app")
