from django.contrib import admin

from apps.audio.models import Album, AudioSource, Playlist, Track, TrackReport


@admin.register(AudioSource)
class AudioSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "node", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("name",)
    raw_id_fields = ("node", "cover", "created_by")


@admin.register(Album)
class AlbumAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "source", "visibility", "published_at")
    list_filter = ("kind", "visibility")
    search_fields = ("title",)
    raw_id_fields = ("source", "cover", "created_by")


@admin.register(Track)
class TrackAdmin(admin.ModelAdmin):
    list_display = ("title", "source", "status", "effective_visibility", "published_at", "version")
    list_filter = ("status", "effective_visibility")
    search_fields = ("title",)
    raw_id_fields = ("source", "album", "raw_file", "uploaded_by")
    exclude = ("search_vector", "embedding")


@admin.register(Playlist)
class PlaylistAdmin(admin.ModelAdmin):
    list_display = ("title", "source", "visibility")
    raw_id_fields = ("owner", "source", "cover")


@admin.register(TrackReport)
class TrackReportAdmin(admin.ModelAdmin):
    list_display = ("track", "reason", "status", "created_at")
    list_filter = ("status", "reason")
    raw_id_fields = ("track", "reporter", "handled_by")
