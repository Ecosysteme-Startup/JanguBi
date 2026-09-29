from rest_framework import serializers

from apps.rosary.models import Mystery, MysteryGroup, MysteryPrayer, Prayer, RosaryDay


class PrayerSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source="get_type_display", read_only=True)

    class Meta:
        model = Prayer
        fields = ("id", "type", "type_display", "language", "text", "source")


class SearchPrayerSerializer(PrayerSerializer):
    """Extends PrayerSerializer to show rank from full text search."""
    rank = serializers.FloatField(read_only=True, required=False)

    class Meta(PrayerSerializer.Meta):
        fields = PrayerSerializer.Meta.fields + ("rank",)  # type: ignore[assignment]  # DRF Meta.fields override widens the base tuple


class MysteryPrayerSerializer(serializers.ModelSerializer):
    prayer = PrayerSerializer(read_only=True)

    class Meta:
        model = MysteryPrayer
        fields = ("order", "prayer")


class MysterySerializer(serializers.ModelSerializer):
    audio_file = serializers.FileField(read_only=True)
    prayers = serializers.SerializerMethodField()

    class Meta:
        model = Mystery
        fields = ("id", "order", "title", "meditation", "meditation_source", "fruit", "audio_file", "audio_duration", "prayers")

    def get_prayers(self, obj):
        # Conditionally include prayers only if prefetch_prayers was used or flag requested
        # Or just include them if they've been prefetched.
        if hasattr(obj, "_prefetched_objects_cache") and "prayers" in obj._prefetched_objects_cache:
            return MysteryPrayerSerializer(obj.prayers.all(), many=True).data
        return []


class GroupSerializer(serializers.ModelSerializer):
    mysteries = serializers.SerializerMethodField()
    audio_file = serializers.FileField(read_only=True)

    class Meta:
        model = MysteryGroup
        fields = ("id", "name", "slug", "audio_file", "mysteries")

    def get_mysteries(self, obj):
        if hasattr(obj, "_prefetched_objects_cache") and "mysteries" in obj._prefetched_objects_cache:
            return MysterySerializer(obj.mysteries.all(), many=True).data
        return []


class RosaryDaySerializer(serializers.ModelSerializer):
    weekday_display = serializers.CharField(source="get_weekday_display", read_only=True)
    group = GroupSerializer(read_only=True)

    class Meta:
        model = RosaryDay
        fields = ("id", "weekday", "weekday_display", "group")
