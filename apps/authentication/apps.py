from django.apps import AppConfig


class AuthenticationConfig(AppConfig):
    name = "apps.authentication"

    def ready(self) -> None:
        from apps.authentication import schema  # noqa: F401  (enregistre les extensions OpenAPI)
