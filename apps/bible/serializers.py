from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.bible.models import Book, Chapter, DailyText, Testament, Verse


class TestamentOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = Testament
        fields = ("slug", "name", "order")


class TestamentWithBooksOutputSerializer(serializers.ModelSerializer):
    books = serializers.SerializerMethodField()

    class Meta:
        model = Testament
        fields = ("slug", "name", "order", "books")

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_books(self, obj):
        # We fetch books related to this testament.
        # This will be efficient if Prefetch is used in the view.
        books = obj.books.all()
        return BookMetadataOutputSerializer(books, many=True).data


class BookMetadataOutputSerializer(serializers.ModelSerializer):
    testament: serializers.SlugRelatedField = serializers.SlugRelatedField(read_only=True, slug_field="slug")
    chapter_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Book
        fields = ("id", "name", "slug", "order", "testament", "verse_count", "chapter_count")


class ChapterMetadataOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chapter
        fields = ("number", "name", "verse_count")


class VerseOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = Verse
        fields = ("id", "number", "text")


class SearchVerseOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.IntegerField()
    chapter = serializers.DictField()  # {'number': X}
    text = serializers.CharField()


class SearchMatchOutputSerializer(serializers.Serializer):
    """Shape of the search result specific to a matching verse."""

    verse = SearchVerseOutputSerializer()
    # Some results (especially hybrid) might bring custom fields like score or no_internal_source
    no_internal_source = serializers.BooleanField(required=False, default=False)
    score = serializers.FloatField(required=False)


class SearchBookMetadataOutputSerializer(serializers.Serializer):
    """Shape of book metadata returned by search service."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    order = serializers.IntegerField()
    testament = serializers.CharField()


class SearchBookGroupOutputSerializer(serializers.Serializer):
    """Shape of search results grouped by book."""

    book = SearchBookMetadataOutputSerializer()
    matches = SearchMatchOutputSerializer(many=True)


class DailyTextOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyText
        fields = ("date", "category", "title", "content", "source_url", "local_matches")
