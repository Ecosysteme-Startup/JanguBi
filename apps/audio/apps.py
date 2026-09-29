from django.apps import AppConfig


class AudioConfig(AppConfig):
    name = "apps.audio"
    verbose_name = "Sonothèque paroissiale"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # Recherche tolérante aux fautes (pg_trgm) sur le titre des pistes, sans installer
        # django.contrib.postgres pour tout le projet : lookups enregistrés sur ce champ seulement.
        from django.contrib.postgres.lookups import TrigramSimilar, TrigramWordSimilar

        from apps.audio.models import Track

        title = Track._meta.get_field("title")
        title.register_lookup(TrigramSimilar)
        title.register_lookup(TrigramWordSimilar)
