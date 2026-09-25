from django.urls import path

from apps.news import apis

urlpatterns = [
    path("", apis.ArticleListApi.as_view(), name="list"),
    path("categories/", apis.CategoryListApi.as_view(), name="category-list"),
    path("<uuid:article_id>/", apis.ArticleDetailApi.as_view(), name="detail"),
    path("<uuid:article_id>/read/", apis.ArticleReadApi.as_view(), name="read"),
    path("<uuid:article_id>/reactions/", apis.ArticleReactionApi.as_view(), name="reactions"),
]
