from django.urls import path

from apps.bible.apis import (
    HomilieNoteDetailApi,
    HomilieNoteListCreateApi,
    LectioDivinaSessionApi,
    ReadingPlanDetailApi,
    ReadingPlanListCreateApi,
    ReadingPlanSubscribeApi,
    ReadingPlanUnsubscribeApi,
)
from apps.bible.views import (
    BookDetailApi,
    BookListApi,
    ChapterListApi,
    DailyTextListApi,
    ImportApi,
    SearchApi,
    TestamentBooksApi,
    TestamentListApi,
    VerseListApi,
)
from apps.core.modules import is_module_active

urlpatterns = [
    # Testaments
    path("testaments/", TestamentListApi.as_view(), name="testament-list"),
    path("testaments/<slug:testament_slug>/books/", TestamentBooksApi.as_view(), name="testament-books"),

    # Books
    path("books/", BookListApi.as_view(), name="book-list"),
    path("books/<int:book_id>/", BookDetailApi.as_view(), name="book-detail"),
    path("books/<int:book_id>/chapters/", ChapterListApi.as_view(), name="chapter-list"),
    path("books/<int:book_id>/chapters/<int:chapter_number>/verses/", VerseListApi.as_view(), name="verse-list"),

    # Search
    path("search/", SearchApi.as_view(), name="search"),

    # Daily Texts
    path("daily-texts/", DailyTextListApi.as_view(), name="daily-text-list"),

    # Internal Tools
    path("import/", ImportApi.as_view(), name="import-file"),
]

# Bible avancée (M7) — gelée en V1 (ADR-006, sous-module « bible.avance »).
if is_module_active("bible.avance"):
    urlpatterns += [
        path("homilenotes/", HomilieNoteListCreateApi.as_view(), name="homilenote-list-create"),
        path("homilenotes/<int:note_id>/", HomilieNoteDetailApi.as_view(), name="homilenote-detail"),
        path("lectio/", LectioDivinaSessionApi.as_view(), name="lectio-divina"),
        path("reading-plans/", ReadingPlanListCreateApi.as_view(), name="reading-plan-list-create"),
        path("reading-plans/<int:plan_id>/", ReadingPlanDetailApi.as_view(), name="reading-plan-detail"),
        path("reading-plans/<int:plan_id>/publish/", ReadingPlanDetailApi.as_view(), name="reading-plan-publish"),
        path("reading-plans/<int:plan_id>/subscribe/", ReadingPlanSubscribeApi.as_view(), name="reading-plan-subscribe"),
        path("reading-plans/<int:plan_id>/unsubscribe/", ReadingPlanUnsubscribeApi.as_view(), name="reading-plan-unsubscribe"),
    ]
