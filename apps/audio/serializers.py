"""Sonothèque : validation des entrées et mise en forme des sorties. Aucune logique.

Tous les composants sont préfixés « Audio » pour éviter les collisions de noms dans le schéma.
"""

from typing import Any

from django.conf import settings
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.audio.enums import (
    AlbumKind,
    EncodingStep,
    Language,
    LiturgicalSeason,
    PlayEventKind,
    ReportReason,
    ReportStatus,
    ReportTarget,
    SourceKind,
    TrackStatus,
    Visibility,
)
from apps.audio.models import Album, AudioSource, Playlist, Track, TrackReport

REPORT_DECISIONS = [
    (ReportStatus.RETIRE.value, ReportStatus.RETIRE.label),
    (ReportStatus.REJETE.value, ReportStatus.REJETE.label),
]


def _cover_url(obj: Any) -> str | None:
    cover = getattr(obj, "cover", None)
    if cover is None or not cover.file:
        return None
    return cover.url


# --- Sorties ---------------------------------------------------------------------------------


class AudioNodeRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class AudioSourceRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = AudioSource
        fields = ("id", "name", "kind")


class AudioSourceSerializer(serializers.ModelSerializer):
    node = AudioNodeRefSerializer()
    cover_url = serializers.SerializerMethodField()

    class Meta:
        model = AudioSource
        fields = ("id", "name", "kind", "description", "node", "cover_url", "is_active")

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_cover_url(self, obj: AudioSource) -> str | None:
        return _cover_url(obj)


class AudioAlbumRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Album
        fields = ("id", "title", "kind")


class AudioAlbumSerializer(serializers.ModelSerializer):
    source = AudioSourceRefSerializer()  # type: ignore[assignment]
    cover_url = serializers.SerializerMethodField()

    class Meta:
        model = Album
        fields = (
            "id", "source", "kind", "title", "description", "visibility", "cover_url", "recorded_on",
            "liturgical_season", "published_at",
        )  # fmt: skip

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_cover_url(self, obj: Album) -> str | None:
        return _cover_url(obj)


class AudioTrackSerializer(serializers.ModelSerializer):
    """Piste vue par un auditeur (aucun compteur : pas de palmarès)."""

    source = AudioSourceRefSerializer()  # type: ignore[assignment]
    album = AudioAlbumRefSerializer(allow_null=True)
    visibility = serializers.CharField(source="effective_visibility")

    class Meta:
        model = Track
        fields = (
            "id", "title", "performers", "composer", "language", "liturgical_season", "tags", "description",
            "duration_seconds", "source", "album", "position", "visibility", "published_at",
        )  # fmt: skip


class AudioStaffTrackSerializer(AudioTrackSerializer):
    """Piste vue par le staff de la source : état et progression de l'encodage, visibilités,
    version, écoutes des 30 derniers jours (listes staff seulement)."""

    own_visibility = serializers.CharField(source="visibility")
    encoding_step = serializers.ChoiceField(
        choices=EncodingStep.choices, allow_blank=True, help_text="Étape en cours ; vide avant le début de l'encodage"
    )
    encoding_percent = serializers.IntegerField(min_value=0, max_value=100)
    plays_30d = serializers.SerializerMethodField()

    class Meta(AudioTrackSerializer.Meta):
        fields: tuple[str, ...] = (  # type: ignore[assignment]
            *AudioTrackSerializer.Meta.fields,
            "own_visibility", "status", "failure_reason", "encoding_step", "encoding_percent", "version",
            "encoded_version", "encoded_at", "hidden_at", "created_at", "plays_30d",
        )  # fmt: skip

    @extend_schema_field(
        serializers.IntegerField(
            allow_null=True, help_text="Débuts d'écoute des 30 derniers jours (listes staff) ; null ailleurs"
        )
    )
    def get_plays_30d(self, obj: Track) -> int | None:
        return getattr(obj, "plays_30d", None)


class AudioStaffAlbumSerializer(AudioAlbumSerializer):
    """Album vu par le staff : brouillons compris, nombre de pistes, retrait par la modération."""

    track_count = serializers.SerializerMethodField()

    class Meta(AudioAlbumSerializer.Meta):
        fields: tuple[str, ...] = (  # type: ignore[assignment]
            *AudioAlbumSerializer.Meta.fields, "track_count", "hidden_at", "created_at", "updated_at",
        )  # fmt: skip

    def get_track_count(self, obj: Album) -> int:
        count = getattr(obj, "track_count", None)
        return obj.tracks.count() if count is None else int(count)


class AudioStaffAlbumDetailSerializer(serializers.Serializer):
    album = AudioStaffAlbumSerializer()
    tracks = AudioStaffTrackSerializer(many=True)


class AudioPlaylistSerializer(serializers.ModelSerializer):
    source = AudioSourceRefSerializer(allow_null=True)  # type: ignore[assignment]
    is_editorial = serializers.SerializerMethodField()
    track_count = serializers.SerializerMethodField()

    class Meta:
        model = Playlist
        fields = ("id", "title", "description", "visibility", "is_editorial", "source", "track_count", "updated_at")

    def get_is_editorial(self, obj: Playlist) -> bool:
        return obj.source_id is not None

    def get_track_count(self, obj: Playlist) -> int:
        return obj.items.count()


class AudioPlaylistDetailSerializer(serializers.Serializer):
    playlist = AudioPlaylistSerializer()
    tracks = AudioTrackSerializer(many=True)


class AudioSourceDetailSerializer(serializers.Serializer):
    source = AudioSourceSerializer()  # type: ignore[assignment]
    albums = AudioAlbumSerializer(many=True)
    playlists = AudioPlaylistSerializer(many=True)
    recent = AudioTrackSerializer(many=True, help_text="Dernières publications de la source")
    most_played = AudioTrackSerializer(many=True, help_text="Les plus écoutés, à l'intérieur de cette source seulement")


class AudioAlbumDetailSerializer(serializers.Serializer):
    album = AudioAlbumSerializer()
    tracks = AudioTrackSerializer(many=True)


class AudioStreamSerializer(serializers.Serializer):
    format = serializers.CharField(help_text="« hls »")
    master_url = serializers.URLField(help_text="master.m3u8 signé (préfixe versionné, 6 h)")
    mp3_url = serializers.URLField(help_text="MP3 128 kb/s pour l'écoute hors ligne (même signature)")
    expires_at = serializers.DateTimeField()


class AudioResumeSerializer(serializers.Serializer):
    position_seconds = serializers.FloatField()
    device_id = serializers.CharField()
    updated_at = serializers.DateTimeField(source="client_updated_at")


class AudioPlaybackSerializer(serializers.Serializer):
    track = AudioTrackSerializer()
    stream = AudioStreamSerializer()
    resume = AudioResumeSerializer(allow_null=True)
    waveform = serializers.ListField(child=serializers.FloatField(), help_text="200 pics entre 0 et 1")


class AudioPlaybackStateSerializer(serializers.Serializer):
    track = AudioTrackSerializer()
    position_seconds = serializers.FloatField()
    device_id = serializers.CharField()
    updated_at = serializers.DateTimeField(source="client_updated_at")


class AudioPlaybackStateWriteOutputSerializer(serializers.Serializer):
    applied = serializers.BooleanField(help_text="Faux si un autre appareil a écrit plus récemment")
    state = AudioPlaybackStateSerializer()


class AudioUploadOutputSerializer(serializers.Serializer):
    upload_id = serializers.UUIDField(help_text="Identifiant de l'envoi (= identifiant de la piste)")
    track = AudioStaffTrackSerializer()
    method = serializers.CharField()
    url = serializers.URLField()
    fields = serializers.DictField(  # type: ignore[assignment]  # clé imposée par le POST présigné S3
        child=serializers.CharField(), help_text="Champs du formulaire POST présigné"
    )
    max_size = serializers.IntegerField()
    expires_in = serializers.IntegerField()


class AudioSearchOutputSerializer(serializers.Serializer):
    results = AudioTrackSerializer(many=True)
    next_cursor = serializers.CharField(allow_null=True)


class AudioRecommendationSerializer(serializers.Serializer):
    track = AudioTrackSerializer()
    reason = serializers.CharField(help_text="Explication lisible, ex. « Parce que vous avez écouté … »")


class AudioForYouSerializer(serializers.Serializer):
    personnalise = serializers.BooleanField()
    demarrage_a_froid = serializers.BooleanField()
    results = AudioRecommendationSerializer(many=True)


class AudioRecentSerializer(serializers.Serializer):
    track = AudioTrackSerializer()
    position_seconds = serializers.FloatField()
    updated_at = serializers.DateTimeField()


class AudioLibrarySerializer(serializers.Serializer):
    likes = AudioTrackSerializer(many=True)
    playlists = AudioPlaylistSerializer(many=True)
    recent = AudioRecentSerializer(many=True)


class AudioEventsResultSerializer(serializers.Serializer):
    recus = serializers.IntegerField()
    enregistres = serializers.IntegerField()
    doublons = serializers.IntegerField()
    rejetes = serializers.IntegerField()


class AudioLikeOutputSerializer(serializers.Serializer):
    liked = serializers.BooleanField()


class AudioListenerSettingsSerializer(serializers.Serializer):
    recommendations_enabled = serializers.BooleanField()


class AudioReportSerializer(serializers.ModelSerializer):
    cible = serializers.SerializerMethodField()
    track = AudioTrackSerializer(allow_null=True)
    album = AudioAlbumSerializer(allow_null=True)
    motif = serializers.ChoiceField(source="reason", choices=ReportReason.choices)

    class Meta:
        model = TrackReport
        fields = ("id", "cible", "track", "album", "motif", "comment", "status", "created_at", "handled_at")

    @extend_schema_field(serializers.ChoiceField(choices=ReportTarget.choices))
    def get_cible(self, obj: TrackReport) -> str:
        return ReportTarget.PISTE if obj.track_id else ReportTarget.ALBUM


class AudioCoverUploadOutputSerializer(serializers.Serializer):
    file_id = serializers.IntegerField(help_text="À renvoyer à « terminer »")
    method = serializers.CharField()
    url = serializers.URLField()
    fields = serializers.DictField(  # type: ignore[assignment]  # clé imposée par le POST présigné S3
        child=serializers.CharField(), help_text="Champs du formulaire POST présigné"
    )
    max_size = serializers.IntegerField()
    expires_in = serializers.IntegerField()


class AudioHomeSeasonSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="avent, noel, careme, triduum, paques, ordinaire")
    label = serializers.CharField(help_text="« Temps ordinaire »…")  # type: ignore[assignment]
    tracks = AudioTrackSerializer(many=True)


class AudioHomeParishSerializer(serializers.Serializer):
    nouveautes_ma_paroisse = AudioTrackSerializer(many=True)
    playlists_paroisse = AudioPlaylistSerializer(many=True)
    temps_liturgique = AudioHomeSeasonSerializer()


class AudioHomeSerializer(AudioHomeParishSerializer):
    paroisse = AudioNodeRefSerializer(allow_null=True, help_text="Paroisse suivie ; null sans compte ou sans paroisse")
    reprendre = AudioRecentSerializer(many=True)
    pour_vous = AudioRecommendationSerializer(many=True)


# --- Entrées ---------------------------------------------------------------------------------


class AudioSourceListFilterSerializer(serializers.Serializer):
    node = serializers.UUIDField(required=False)
    kind = serializers.ChoiceField(choices=SourceKind.choices, required=False)


class AudioSourceCreateInputSerializer(serializers.Serializer):
    node_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=SourceKind.choices)
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")


class AudioSourceUpdateInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=SourceKind.choices, required=False)
    name = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)


class AudioAlbumListFilterSerializer(serializers.Serializer):
    source = serializers.UUIDField(required=False)  # type: ignore[assignment]
    kind = serializers.ChoiceField(choices=AlbumKind.choices, required=False)


class AudioAlbumInputSerializer(serializers.Serializer):
    source_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=AlbumKind.choices, default=AlbumKind.ALBUM)
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    visibility = serializers.ChoiceField(choices=Visibility.choices, default=Visibility.PRIVE)
    recorded_on = serializers.DateField(required=False, allow_null=True)
    liturgical_season = serializers.ChoiceField(choices=LiturgicalSeason.choices, required=False, allow_blank=True)


class AudioAlbumUpdateInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=AlbumKind.choices, required=False)
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    visibility = serializers.ChoiceField(choices=Visibility.choices, required=False)
    recorded_on = serializers.DateField(required=False, allow_null=True)
    liturgical_season = serializers.ChoiceField(choices=LiturgicalSeason.choices, required=False, allow_blank=True)


class AudioTrackUpdateInputSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=250, required=False)
    performers = serializers.ListField(child=serializers.CharField(max_length=150), required=False, max_length=20)
    composer = serializers.CharField(max_length=200, required=False, allow_blank=True)
    language = serializers.ChoiceField(choices=Language.choices, required=False)
    liturgical_season = serializers.ChoiceField(choices=LiturgicalSeason.choices, required=False, allow_blank=True)
    tags = serializers.ListField(child=serializers.CharField(max_length=60), required=False, max_length=30)
    description = serializers.CharField(required=False, allow_blank=True)
    visibility = serializers.ChoiceField(choices=Visibility.choices, required=False)
    position = serializers.IntegerField(min_value=0, required=False)
    album_id = serializers.UUIDField(required=False, allow_null=True)


class AudioUploadInputSerializer(serializers.Serializer):
    source_id = serializers.UUIDField()
    album_id = serializers.UUIDField(required=False, allow_null=True)
    title = serializers.CharField(max_length=250, required=False, allow_blank=True, default="")
    visibility = serializers.ChoiceField(choices=Visibility.choices, default=Visibility.PUBLIC)
    file_name = serializers.CharField(max_length=255)
    file_type = serializers.CharField(max_length=100)
    file_size = serializers.IntegerField(min_value=1, help_text="Octets ; 500 Mo au plus")
    rights_confirmed = serializers.BooleanField(help_text="Case « J'ai les droits sur cet enregistrement » (obligatoire)")


class AudioStaffAlbumFilterSerializer(serializers.Serializer):
    source = serializers.UUIDField(required=False)  # type: ignore[assignment]
    kind = serializers.ChoiceField(choices=AlbumKind.choices, required=False)


class AudioCoverUploadInputSerializer(serializers.Serializer):
    file_name = serializers.CharField(max_length=255)
    file_type = serializers.CharField(max_length=100, help_text="image/jpeg, image/png ou image/webp")
    file_size = serializers.IntegerField(min_value=1, help_text="Octets ; 5 Mo au plus")


class AudioCoverFinishInputSerializer(serializers.Serializer):
    file_id = serializers.IntegerField(min_value=1)


class AudioLocalUploadInputSerializer(serializers.Serializer):
    file = serializers.FileField()


class AudioStaffTrackFilterSerializer(serializers.Serializer):
    source = serializers.UUIDField()  # type: ignore[assignment]
    status = serializers.ChoiceField(choices=TrackStatus.choices, required=False)


class AudioPlaybackStateInputSerializer(serializers.Serializer):
    track_id = serializers.UUIDField()
    position_seconds = serializers.FloatField(min_value=0)
    device_id = serializers.CharField(max_length=100)
    client_updated_at = serializers.DateTimeField(help_text="Horodatage de l'appareil (borné par le serveur)")


class AudioSearchQuerySerializer(serializers.Serializer):
    q = serializers.CharField(max_length=200)
    cursor = serializers.CharField(required=False, allow_blank=True, default="")
    limit = serializers.IntegerField(required=False, min_value=1, max_value=50, default=20)


class AudioEventInputSerializer(serializers.Serializer):
    client_event_id = serializers.UUIDField()
    track_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=PlayEventKind.choices)
    occurred_at = serializers.DateTimeField()
    position_seconds = serializers.FloatField(min_value=0, required=False, default=0)
    device_id = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class AudioEventsInputSerializer(serializers.Serializer):
    events = AudioEventInputSerializer(  # type: ignore[call-arg]  # max_length : DRF ≥ 3.14, absent des stubs
        many=True, allow_empty=False, max_length=settings.AUDIO_EVENTS_MAX_BATCH
    )


class AudioPlaylistInputSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    visibility = serializers.ChoiceField(choices=Visibility.choices, default=Visibility.PRIVE)
    source_id = serializers.UUIDField(required=False, allow_null=True, help_text="Playlist éditoriale de la source")


class AudioPlaylistUpdateInputSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    visibility = serializers.ChoiceField(choices=Visibility.choices, required=False)
    published = serializers.BooleanField(required=False, help_text="Playlist éditoriale : publiée ou non")


class AudioPlaylistAddInputSerializer(serializers.Serializer):
    track_id = serializers.UUIDField()


class AudioPlaylistOrderInputSerializer(serializers.Serializer):
    track_ids = serializers.ListField(child=serializers.UUIDField(), max_length=1000)


class AudioReportInputSerializer(serializers.Serializer):
    motif = serializers.ChoiceField(choices=ReportReason.choices)
    comment = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)


class AudioReportDecisionInputSerializer(serializers.Serializer):
    resolution = serializers.ChoiceField(choices=REPORT_DECISIONS)
