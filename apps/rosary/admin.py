from django.contrib import admin

from apps.rosary.models import Mystery, MysteryGroup, MysteryPrayer, Prayer, RosaryDay


@admin.register(MysteryGroup)
class MysteryGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


class MysteryPrayerInline(admin.TabularInline):
    model = MysteryPrayer
    extra = 1


@admin.register(Mystery)
class MysteryAdmin(admin.ModelAdmin):
    list_display = ("title", "group", "order", "audio_file")
    list_filter = ("group",)
    search_fields = ("title",)
    inlines = [MysteryPrayerInline]


@admin.register(Prayer)
class PrayerAdmin(admin.ModelAdmin):
    list_display = ("get_type_display", "language", "text_snippet")
    list_filter = ("type", "language")
    search_fields = ("text",)

    def text_snippet(self, obj):
        return obj.text[:50] + "..." if len(obj.text) > 50 else obj.text

    text_snippet.short_description = "Text"  # type: ignore[attr-defined]  # Django admin display-method attribute


@admin.register(RosaryDay)
class RosaryDayAdmin(admin.ModelAdmin):
    list_display = ("get_weekday_display", "group")
    list_filter = ("weekday", "group")
