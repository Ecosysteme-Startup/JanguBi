from django.urls import path

from apps.intentions import apis

urlpatterns = [
    path("", apis.IntentionCreateApi.as_view(), name="create"),
    path("notice/", apis.NoticeApi.as_view(), name="notice"),
    path("mine/", apis.MyIntentionsApi.as_view(), name="mine"),
    path("parish/", apis.ParishIntentionsApi.as_view(), name="parish"),
    path("<uuid:intention_id>/cancel/", apis.IntentionCancelApi.as_view(), name="cancel"),
    path("<uuid:intention_id>/accept/", apis.IntentionAcceptApi.as_view(), name="accept"),
    path("<uuid:intention_id>/decline/", apis.IntentionDeclineApi.as_view(), name="decline"),
    path("<uuid:intention_id>/celebrate/", apis.IntentionCelebrateApi.as_view(), name="celebrate"),
]
