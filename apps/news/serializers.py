from typing import Any

from rest_framework import serializers

from apps.news.models import Article, ArticleCategory, ArticleReaction

_REACTION_TYPES: tuple[str, ...] = tuple(ArticleReaction.ReactionType.values)
V1_TYPES = [(Article.ContentType.ANNOUNCEMENT, "Annonce"), (Article.ContentType.ARTICLE, "Article")]


def _author_display(user: Any) -> str:
    profile = getattr(user, "profile", None)
    name = f"{getattr(profile, 'first_name', '')} {getattr(profile, 'last_name', '')}".strip()
    return name or "Jàngu Bi"


# --- Sorties ------------------------------------------------------------------------------


class CategoryOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArticleCategory
        fields = ["id", "name", "slug", "icon", "color", "display_order"]


class ArticleReactionsOutputSerializer(serializers.Serializer):
    counts = serializers.DictField(child=serializers.IntegerField(), help_text="pray / amen / attend")
    mine = serializers.ListField(child=serializers.ChoiceField(choices=ArticleReaction.ReactionType.choices))


class ScopeOutputSerializer(serializers.Serializer):
    node_id = serializers.UUIDField(allow_null=True)
    node_name = serializers.CharField(allow_null=True)
    place_id = serializers.IntegerField(allow_null=True)
    place_name = serializers.CharField(allow_null=True)


class ArticleOutputSerializer(serializers.ModelSerializer):
    """Vue publique : jamais le compteur de lectures (réservé au staff, EF-PAROI-05)."""

    category = CategoryOutputSerializer(read_only=True)
    author_name = serializers.SerializerMethodField()
    scope = serializers.SerializerMethodField()
    cover_image_url = serializers.SerializerMethodField()
    reactions = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = [
            "id",
            "content_type",
            "title",
            "slug",
            "excerpt",
            "content",
            "content_format",
            "category",
            "author_name",
            "scope",
            "is_sunday_notice",
            "sunday_date",
            "cover_image_url",
            "published_at",
            "reactions",
        ]

    def get_author_name(self, obj: Article) -> str:
        return _author_display(obj.author)

    def get_scope(self, obj: Article) -> dict[str, Any]:
        return ScopeOutputSerializer(
            {
                "node_id": obj.scope_node_id,
                "node_name": obj.scope_node.name if obj.scope_node else None,
                "place_id": obj.scope_place_id,
                "place_name": obj.scope_place.name if obj.scope_place else None,
            }
        ).data

    def get_cover_image_url(self, obj: Article) -> str | None:
        return obj.cover_image.url if obj.cover_image else None

    def get_reactions(self, obj: Article) -> dict[str, Any]:
        return {
            "counts": {t: getattr(obj, f"reactions_{t}", 0) or 0 for t in _REACTION_TYPES},
            "mine": [t for t in _REACTION_TYPES if getattr(obj, f"mine_{t}", False)],
        }


class ArticleListOutputSerializer(ArticleOutputSerializer):
    class Meta(ArticleOutputSerializer.Meta):
        fields = [f for f in ArticleOutputSerializer.Meta.fields if f != "content"]


class StaffArticleOutputSerializer(serializers.ModelSerializer):
    category = CategoryOutputSerializer(read_only=True)
    author_name = serializers.SerializerMethodField()
    scope = serializers.SerializerMethodField()
    reads_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Article
        fields = [
            "id",
            "content_type",
            "title",
            "slug",
            "excerpt",
            "content",
            "content_format",
            "category",
            "author_name",
            "scope",
            "is_sunday_notice",
            "sunday_date",
            "status",
            "publish_at",
            "published_at",
            "unpublished_at",
            "unpublish_reason",
            "reads_count",
            "created_at",
            "updated_at",
        ]

    get_author_name = ArticleOutputSerializer.get_author_name
    get_scope = ArticleOutputSerializer.get_scope


# --- Entrées -------------------------------------------------------------------------------


class ArticleFilterSerializer(serializers.Serializer):
    node = serializers.UUIDField(required=False, help_text="Nœud (et son sous-arbre)")
    sunday = serializers.DateField(required=False, help_text="Annonces du dimanche de cette date")
    type = serializers.ChoiceField(choices=V1_TYPES, required=False)
    category = serializers.IntegerField(required=False)


class StaffArticleFilterSerializer(serializers.Serializer):
    node = serializers.UUIDField(required=False)
    status = serializers.ChoiceField(choices=Article.Status.choices, required=False)
    type = serializers.ChoiceField(choices=V1_TYPES, required=False)


class ArticleCreateInputSerializer(serializers.Serializer):
    node_id = serializers.UUIDField(required=False, allow_null=True, help_text="Vide : contenu global (plateforme)")
    place_id = serializers.IntegerField(required=False, allow_null=True)
    content_type = serializers.ChoiceField(choices=V1_TYPES, default=Article.ContentType.ANNOUNCEMENT)
    title = serializers.CharField(max_length=200)
    excerpt = serializers.CharField(max_length=400, required=False, allow_blank=True, default="")
    content = serializers.CharField()
    content_format = serializers.ChoiceField(choices=Article.ContentFormat.choices, default=Article.ContentFormat.TEXT)
    category_id = serializers.IntegerField()
    is_sunday_notice = serializers.BooleanField(default=False)
    sunday_date = serializers.DateField(required=False, allow_null=True)


class ArticleUpdateInputSerializer(serializers.Serializer):
    content_type = serializers.ChoiceField(choices=V1_TYPES, required=False)
    title = serializers.CharField(max_length=200, required=False)
    excerpt = serializers.CharField(max_length=400, required=False, allow_blank=True)
    content = serializers.CharField(required=False)
    content_format = serializers.ChoiceField(choices=Article.ContentFormat.choices, required=False)
    category_id = serializers.IntegerField(required=False)
    is_sunday_notice = serializers.BooleanField(required=False)
    sunday_date = serializers.DateField(required=False, allow_null=True)


class ArticlePublishInputSerializer(serializers.Serializer):
    publish_at = serializers.DateTimeField(required=False, allow_null=True, help_text="Futur : publication programmée")


class ArticleUnpublishInputSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class ReactionInputSerializer(serializers.Serializer):
    reaction_type = serializers.ChoiceField(choices=ArticleReaction.ReactionType.choices)
    active = serializers.BooleanField()


class ReadOutputSerializer(serializers.Serializer):
    first_read = serializers.BooleanField()
