from django.urls import path

from apps.core.modules import is_module_active
from apps.rosary.community_apis import (
    CommunityRosaryEndApi,
    CommunityRosaryIntentionApi,
    CommunityRosaryJoinApi,
    CommunityRosaryListCreateApi,
)
from apps.rosary.views import (
    GroupDetailApi,
    GroupListApi,
    MysteryDetailApi,
    PrayerListApi,
    RosarySearchApi,
    RosaryWeekdayApi,
    TodayRosaryApi,
)

urlpatterns = [
    # Groups
    path("groups/", GroupListApi.as_view(), name="group-list"),
    path("groups/<slug:slug>/", GroupDetailApi.as_view(), name="group-detail"),
    # Days
    path("today/", TodayRosaryApi.as_view(), name="today-rosary"),
    path("day/<int:day>/", RosaryWeekdayApi.as_view(), name="day-rosary"),
    # Core Components
    path("prayers/", PrayerListApi.as_view(), name="prayer-list"),
    path("mysteries/<int:pk>/", MysteryDetailApi.as_view(), name="mystery-detail"),
    # Search
    path("search/", RosarySearchApi.as_view(), name="search"),
]

# Chapelet communautaire (M8) — gelé en V1 (ADR-006, « rosary.communautaire »).
if is_module_active("rosary.communautaire"):
    urlpatterns += [
        path("community/", CommunityRosaryListCreateApi.as_view(), name="community-list-create"),
        path("community/<int:rosary_id>/join/", CommunityRosaryJoinApi.as_view(), name="community-join"),
        path(
            "community/<int:rosary_id>/intentions/", CommunityRosaryIntentionApi.as_view(), name="community-intentions"
        ),
        path("community/<int:rosary_id>/end/", CommunityRosaryEndApi.as_view(), name="community-end"),
    ]
