from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.bible.serializers import VerseOutputSerializer
from apps.liturgy.models import AelfResource, LiturgicalDate, Office, Reading


class ReadingSerializer(serializers.ModelSerializer):
    """Serializer for Mass readings."""

    matched_verses = VerseOutputSerializer(many=True, read_only=True)

    class Meta:
        model = Reading
        fields = ("id", "type", "citation", "text", "raw_metadata", "matched_verses")


class OfficeSerializer(serializers.ModelSerializer):
    """Serializer for Liturgy of the Hours texts."""

    class Meta:
        model = Office
        fields = ("id", "office_type", "hymn", "psalms", "canticle", "readings", "intercessions", "raw_metadata")


class AelfResourceSerializer(serializers.ModelSerializer):
    """Serializer for external AELF resources (audio/youtube)."""

    class Meta:
        model = AelfResource
        fields = ("audio_url", "youtube_url")


class LiturgicalDateSerializer(serializers.ModelSerializer):
    """
    Main serializer aggregating all data for a specific liturgical date.
    Includes nested resources, readings, and offices if prefetched.
    """

    resource = AelfResourceSerializer(read_only=True)
    readings = serializers.SerializerMethodField()
    offices = serializers.SerializerMethodField()

    class Meta:
        model = LiturgicalDate
        fields = ("id", "date", "zone", "day_name", "season", "mystery", "notes", "resource", "readings", "offices")

    @extend_schema_field(ReadingSerializer(many=True))
    def get_readings(self, obj):
        # Prevent N+1 queries by relying on explicit prefetching in the view
        if hasattr(obj, "_prefetched_objects_cache") and "readings" in obj._prefetched_objects_cache:
            return ReadingSerializer(obj.readings.all(), many=True).data
        return []

    @extend_schema_field(OfficeSerializer(many=True))
    def get_offices(self, obj):
        # Prevent N+1 queries by relying on explicit prefetching in the view
        if hasattr(obj, "_prefetched_objects_cache") and "offices" in obj._prefetched_objects_cache:
            return OfficeSerializer(obj.offices.all(), many=True).data
        return []
