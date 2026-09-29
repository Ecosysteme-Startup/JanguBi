import factory
from factory.django import DjangoModelFactory

from apps.news.models import ArticleCategory


class ArticleCategoryFactory(DjangoModelFactory):
    class Meta:
        model = ArticleCategory

    name = factory.Sequence(lambda n: f"Catégorie {n}")
    slug = factory.Sequence(lambda n: f"categorie-{n}")
    icon = ""
    color = ""
    display_order = factory.Sequence(lambda n: n)
    is_active = True


class ArticleFactory(DjangoModelFactory):
    """Brouillon global (écriture directe : pour les tests de migration de données)."""

    class Meta:
        model = "news.Article"

    title = factory.Sequence(lambda n: f"Article test {n}")
    slug = factory.Sequence(lambda n: f"article-test-{n}-global")
    content = factory.Sequence(lambda n: f"Contenu de l'article {n}.")
    category = factory.SubFactory(ArticleCategoryFactory)
    author = factory.SubFactory("apps.users.tests.factories.StaffUserFactory")
    status = "draft"
