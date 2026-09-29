from django.apps import AppConfig


class RealtimeConfig(AppConfig):
    """Temps réel côté serveur (lot B2) : flux SSE et événements des tableaux de bord.

    Les événements des dons sont émis depuis les enregistrements (signaux ``post_save``,
    publiés après la transaction) : le module dons n'a pas à connaître ce transport."""

    name = "apps.realtime"
    verbose_name = "Temps réel"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from apps.realtime import (
            dons,  # noqa: F401 — branche les récepteurs de signaux
            schema,  # noqa: F401 — extension OpenAPI du ticket
        )
