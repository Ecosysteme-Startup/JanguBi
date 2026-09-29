from django.apps import AppConfig


class SearchConfig(AppConfig):
    name = "apps.search"
    label = "search"
    verbose_name = "Recherche transverse"

    def ready(self) -> None:
        # « Therese » trouve « Thérèse » : lookup ``unaccent`` (extension créée par la migration
        # audio 0001) enregistré sur les seuls champs cherchés, comme le fait l'app audio.
        from django.contrib.postgres.lookups import Unaccent

        from apps.hierarchy.models import Node, PlaceOfWorship
        from apps.news.models import Article
        from apps.users.models import Profile

        for model, fields in (
            (Node, ("name", "city")),
            (PlaceOfWorship, ("name", "city")),
            (Article, ("title", "excerpt", "content")),
            (Profile, ("first_name", "last_name")),
        ):
            for name in fields:
                model._meta.get_field(name).register_lookup(Unaccent)  # type: ignore[union-attr]
