from pathlib import Path

from django.conf import settings
from django.db.models import Count, Prefetch
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    OpenApiTypes,
    extend_schema,
    extend_schema_serializer,
)
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin
from apps.api.pagination import LimitOffsetPagination, get_paginated_response, paginated_response_serializer
from apps.bible.editions import edition_filter
from apps.bible.models import Book, Chapter, DailyText, Testament, Verse
from apps.bible.serializers import (
    BookMetadataOutputSerializer,
    ChapterMetadataOutputSerializer,
    DailyTextOutputSerializer,
    SearchBookGroupOutputSerializer,
    TestamentWithBooksOutputSerializer,
    VerseOutputSerializer,
)
from apps.bible.services.search_service import SearchService
from apps.bible.tasks import import_file_task
from apps.hierarchy.authz import HasCapability


class TestamentListApi(APIView):
    """Returns the lists of testaments (Ancien & Nouveau) with nested books."""

    @extend_schema(
        responses=TestamentWithBooksOutputSerializer(many=True),
        tags=["Bible"],
        summary="List testaments with nested books",
    )
    @method_decorator(cache_page(60 * 60 * 24))  # Cache for 24 hours
    def get(self, request):
        testaments = (
            Testament.objects.prefetch_related(
                Prefetch("books", queryset=Book.objects.annotate(chapter_count=Count("chapters")).order_by("order"))
            )
            .all()
            .order_by("order")
        )
        serializer = TestamentWithBooksOutputSerializer(testaments, many=True)
        return Response(serializer.data)


class TestamentBooksApi(APIView):
    """Returns all books for a given testament."""

    @extend_schema(
        responses=BookMetadataOutputSerializer(many=True),
        tags=["Bible"],
        summary="List all books for a specific testament",
    )
    @method_decorator(cache_page(60 * 60 * 24))
    def get(self, request, testament_slug):
        books = Book.objects.filter(testament__slug=testament_slug)
        serializer = BookMetadataOutputSerializer(books, many=True)
        return Response(serializer.data)


class BookListApi(APIView):
    """Returns paginated list of all books, optionally filtered by testament and searched by name."""

    class Pagination(LimitOffsetPagination):
        default_limit = 20

    class FilterSerializer(serializers.Serializer):
        testament = serializers.CharField(required=False, allow_blank=True, allow_null=True)
        search = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    @extend_schema(
        parameters=[
            FilterSerializer,
            OpenApiParameter(
                "limit", OpenApiTypes.INT, description="Number of results to return per page.", required=False
            ),
            OpenApiParameter(
                "offset",
                OpenApiTypes.INT,
                description="The initial index from which to return the results.",
                required=False,
            ),
        ],
        responses=BookMetadataOutputSerializer(many=True),
        tags=["Bible"],
        summary="List all books with optional testament filter and name search",
    )
    @method_decorator(cache_page(60 * 60 * 24))
    def get(self, request):
        filters_serializer = self.FilterSerializer(data=request.query_params)
        filters_serializer.is_valid(raise_exception=True)

        qs = Book.objects.select_related("testament").annotate(chapter_count=Count("chapters"))

        testament_param = filters_serializer.validated_data.get("testament")
        if testament_param:
            qs = qs.filter(testament__slug=testament_param)

        search_param = filters_serializer.validated_data.get("search")
        if search_param:
            qs = qs.filter(name__icontains=search_param)

        return get_paginated_response(
            pagination_class=self.Pagination,
            serializer_class=BookMetadataOutputSerializer,
            queryset=qs,
            request=request,
            view=self,
        )


class BookDetailApi(APIView):
    """Returns metadata for a specific book, optionally expanding chapters."""

    class BookDetailOutputSerializer(BookMetadataOutputSerializer):
        chapters = ChapterMetadataOutputSerializer(many=True, read_only=True)

        class Meta(BookMetadataOutputSerializer.Meta):
            fields = BookMetadataOutputSerializer.Meta.fields + ("chapters",)  # type: ignore[assignment]  # DRF Meta.fields override widens the inherited tuple length

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "expand", OpenApiTypes.STR, description="Pass 'chapters' to include chapters metadata", required=False
            )
        ],
        responses=BookDetailOutputSerializer,
        tags=["Bible"],
        summary="Get book metadata",
    )
    @method_decorator(cache_page(60 * 60 * 1))  # 1 hour
    def get(self, request, book_id):
        expand = request.query_params.get("expand") == "chapters"

        qs = Book.objects.select_related("testament").annotate(chapter_count=Count("chapters"))

        if expand:
            qs = qs.prefetch_related(Prefetch("chapters", queryset=Chapter.objects.order_by("number")))

        try:
            book = qs.get(id=book_id)
        except Book.DoesNotExist:
            return Response({"error": "Book not found"}, status=status.HTTP_404_NOT_FOUND)

        if expand:
            serializer = self.BookDetailOutputSerializer(book)
        else:
            serializer = BookMetadataOutputSerializer(book)

        return Response(serializer.data)


class ChapterListApi(APIView):
    """Returns list of chapters for a book."""

    @extend_schema(
        responses=ChapterMetadataOutputSerializer(many=True),
        tags=["Bible"],
        summary="List chapters for a specific book",
    )
    @method_decorator(cache_page(60 * 60 * 6))
    def get(self, request, book_id):
        chapters = Chapter.objects.filter(book_id=book_id).order_by("number")
        serializer = ChapterMetadataOutputSerializer(chapters, many=True)
        return Response(serializer.data)


class VerseListApi(APIView):
    """Versets d'un chapitre. Une page couvre un chapitre entier (le plus long, Ps 119, a
    176 versets) : ``limit`` vaut 200 par défaut et au plus."""

    class Pagination(LimitOffsetPagination):
        default_limit = 200
        max_limit = 200

    class FilterSerializer(serializers.Serializer):
        excerpt = serializers.BooleanField(required=False, default=False)
        verses = serializers.CharField(required=False, allow_blank=True, allow_null=True)
        source = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)  # type: ignore[assignment]  # drf-stubs: serializer field named "source" collides with Field.source attribute

    @extend_schema(
        parameters=[
            FilterSerializer,
            OpenApiParameter(
                "limit",
                OpenApiTypes.INT,
                description="Versets par page : 200 par défaut et au plus (un chapitre entier).",
                required=False,
            ),
            OpenApiParameter(
                "offset",
                OpenApiTypes.INT,
                description="The initial index from which to return the results.",
                required=False,
            ),
        ],
        responses=paginated_response_serializer(VerseOutputSerializer),
        operation_id="v1_bible_books_chapters_verses_list",
        tags=["Bible"],
        summary="Versets d'un chapitre (le chapitre entier en une requête)",
    )
    @method_decorator(cache_page(60 * 60 * 6))
    def get(self, request, book_id, chapter_number):
        filters_serializer = self.FilterSerializer(data=request.query_params)
        filters_serializer.is_valid(raise_exception=True)

        qs = Verse.objects.filter(chapter__book_id=book_id, chapter__number=chapter_number).order_by("number")

        qs = edition_filter(qs, requested=filters_serializer.validated_data.get("source"))

        verses_param = filters_serializer.validated_data.get("verses")
        if verses_param:
            if "-" in verses_param:
                parts = verses_param.split("-")
                try:
                    start = int(parts[0]) if parts[0].isdigit() else None
                    end = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
                    if start is not None and end is not None:
                        qs = qs.filter(number__gte=start, number__lte=end)
                    elif start is not None:
                        qs = qs.filter(number__gte=start)
                    elif end is not None:
                        qs = qs.filter(number__lte=end)
                except ValueError:
                    pass
            elif verses_param.isdigit():
                qs = qs.filter(number=int(verses_param))

        excerpt = filters_serializer.validated_data.get("excerpt", False)

        paginated_response = get_paginated_response(
            pagination_class=self.Pagination,
            serializer_class=VerseOutputSerializer,
            queryset=qs,
            request=request,
            view=self,
        )

        # If excerpt requested, truncate texts in response data manually
        if excerpt and "results" in paginated_response.data:
            for item in paginated_response.data["results"]:
                text = item["text"]
                if len(text) > 250:
                    item["text"] = text[:247] + "..."

        return paginated_response


class SearchApi(APIView):
    """Recherche dans les versets : plein texte + trigrammes (ADR-018, sans recherche vectorielle)."""

    class InputSerializer(serializers.Serializer):
        # max_length borne le coût de la requête plein texte.
        q = serializers.CharField(min_length=3, max_length=300)
        testament = serializers.CharField(required=False, allow_blank=True, allow_null=True)
        book_slug = serializers.CharField(required=False, allow_blank=True, allow_null=True)
        chapter_number = serializers.IntegerField(required=False, allow_null=True)
        source = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)  # type: ignore[assignment]  # drf-stubs: serializer field named "source" collides with Field.source attribute
        # Conservé pour les anciens clients, sans effet : il n'y a plus de recherche vectorielle (ADR-018).
        hybrid = serializers.BooleanField(default=False, help_text="Sans effet (conservé pour compatibilité).")
        limit = serializers.IntegerField(default=50, max_value=500)

    # Cache for 2-30 min based on query is typically done via vary_on_cookie or query params
    # We use cache_page which automatically varies by GET parameters by default
    @extend_schema(
        parameters=[InputSerializer],
        responses=SearchBookGroupOutputSerializer(many=True),
        tags=["Bible"],
        summary="Recherche plein texte (sans accents, tolérante aux fautes) dans les versets",
    )
    @method_decorator(cache_page(60 * 5))  # 5 minutes
    def get(self, request):
        serializer = self.InputSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        service = SearchService()

        # Fetch results
        results = service.search(
            query=data["q"],
            testament_slug=data.get("testament"),
            book_slug=data.get("book_slug"),
            chapter_number=data.get("chapter_number"),
            source_file=settings.BIBLE_EDITION or data.get("source"),
            limit=data["limit"],
        )

        out_serializer = SearchBookGroupOutputSerializer(results, many=True)
        return Response(out_serializer.data)


class DailyTextListApi(APIView):
    """Returns AELF daily texts."""

    class Pagination(LimitOffsetPagination):
        default_limit = 10

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "limit", OpenApiTypes.INT, description="Number of results to return per page.", required=False
            ),
            OpenApiParameter(
                "offset",
                OpenApiTypes.INT,
                description="The initial index from which to return the results.",
                required=False,
            ),
        ],
        responses=DailyTextOutputSerializer(many=True),
        tags=["Bible"],
        summary="Get paginated list of AELF daily texts",
    )
    def get(self, request):
        qs = DailyText.objects.all().order_by("-date")
        return get_paginated_response(
            pagination_class=self.Pagination,
            serializer_class=DailyTextOutputSerializer,
            queryset=qs,
            request=request,
            view=self,
        )


class ImportApi(ApiAuthMixin, APIView):
    """Import en tâche de fond, réservé à la plateforme (capacité plateforme.admin)."""

    permission_classes = (IsAuthenticated, HasCapability("plateforme.admin"))

    # `component_name` explicite : sans lui, drf-spectacular nomme le composant
    # « Input » comme les serializers imbriqués de apps/files — collision de
    # composants, donc un corps de requête FAUX dans le schéma publié.
    @extend_schema_serializer(component_name="BibleImportInput")
    class InputSerializer(serializers.Serializer):
        filename = serializers.CharField()
        source = serializers.CharField()  # type: ignore[assignment]  # drf-stubs: serializer field named "source" collides with Field.source attribute

    @extend_schema(
        request=InputSerializer,
        responses={
            202: OpenApiResponse(description='Import enqueued — `{"status": ...}`'),
            400: OpenApiResponse(
                description='Nom de fichier invalide (chemin de répertoire interdit) — `{"error": ...}`'
            ),
            403: OpenApiResponse(description="Réservé à la plateforme (plateforme.admin)"),
            404: OpenApiResponse(description='Fichier introuvable dans le dossier d\'importation — `{"error": ...}`'),
        },
        tags=["Bible"],
        summary="Trigger background import of Bible texts",
    )
    def post(self, request):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        filename = data["filename"]

        # SÉCURITÉ : Prévention de Path Traversal
        if "/" in filename or "\\" in filename or ".." in filename:
            return Response(
                {"error": "Le nom du fichier ne doit pas contenir de chemins de répertoire."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        safe_dir = Path(settings.BASE_DIR) / "apps" / "bible" / "data"
        file_path = str(safe_dir / filename)

        if not Path(file_path).exists():
            return Response(
                {"error": f"Le fichier '{filename}' est introuvable dans le dossier d'importation."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Enqueue Celery task
        import_file_task.delay(file_path, data["source"])

        return Response({"status": "Import started in background processing"}, status=status.HTTP_202_ACCEPTED)
