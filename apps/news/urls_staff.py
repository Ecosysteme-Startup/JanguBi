from django.urls import path

from apps.news import apis

urlpatterns = [
    path("", apis.StaffArticleListCreateApi.as_view(), name="list"),
    path("sunday-sheet/", apis.StaffSundaySheetApi.as_view(), name="sunday-sheet"),
    path("<uuid:article_id>/", apis.StaffArticleDetailApi.as_view(), name="detail"),
    path("<uuid:article_id>/publish/", apis.StaffArticlePublishApi.as_view(), name="publish"),
    path("<uuid:article_id>/unpublish/", apis.StaffArticleUnpublishApi.as_view(), name="unpublish"),
]
