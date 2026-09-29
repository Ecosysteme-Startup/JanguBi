from django.contrib import admin

from apps.news.models import Article, ArticleCategory, ArticleReaction


@admin.register(ArticleCategory)
class ArticleCategoryAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "slug", "display_order", "is_active"]
    list_editable = ["display_order", "is_active"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    ordering = ["display_order", "name"]


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "category", "scope_node", "status", "author", "published_at", "created_at"]
    list_filter = ["status", "category"]
    search_fields = ["title", "slug", "content"]
    raw_id_fields = ["author", "cover_image", "unpublished_by", "scope_node", "scope_place"]
    readonly_fields = [
        "id", "slug", "views_count", "published_at", "unpublished_at", "created_at", "updated_at"
    ]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]

    fieldsets = (
        ("Contenu", {"fields": ("title", "slug", "excerpt", "content", "cover_image", "category")}),
        ("Portée", {"fields": ("scope_node", "scope_place")}),
        ("Publication", {"fields": ("status", "author", "published_at")}),
        (
            "Dépublication",
            {
                "fields": ("unpublished_at", "unpublished_by", "unpublish_reason"),
                "classes": ("collapse",),
            },
        ),
        (
            "Métadonnées",
            {
                "fields": ("id", "views_count", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(ArticleReaction)
class ArticleReactionAdmin(admin.ModelAdmin):
    list_display = ["id", "article", "user", "reaction_type", "created_at"]
    list_filter = ["reaction_type", "created_at"]
    search_fields = ["article__title", "user__email"]
    raw_id_fields = ["article", "user"]
    readonly_fields = ["created_at", "updated_at"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]
