"""Sonothèque paroissiale (plan suite V2, §5). Schéma seulement : les règles sont dans ``services``.

La base ne garde que des métadonnées ; les fichiers (source, HLS, MP3, forme d'onde) sont dans le
stockage objet (``audio-raw/`` et ``audio-hls/<track_id>/<version>/``).
"""

import uuid

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.audio.enums import (
    AlbumKind,
    EncodingStep,
    Language,
    LiturgicalSeason,
    NeighborMethod,
    PlayEventKind,
    RenditionKind,
    ReportReason,
    ReportStatus,
    SourceKind,
    TrackStatus,
    Visibility,
)
from apps.common.models import BaseModel


class AudioSource(BaseModel):
    """Qui publie : une paroisse, une chorale ou un mouvement, rattaché à un nœud de la hiérarchie.
    Les droits (``audio.publier``, ``audio.moderer``) et l'appartenance se lisent sur ce nœud."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    node = models.ForeignKey("hierarchy.Node", on_delete=models.PROTECT, related_name="audio_sources")
    kind = models.CharField(_("type"), max_length=20, choices=SourceKind.choices, default=SourceKind.PAROISSE)
    name = models.CharField(_("nom"), max_length=200)
    description = models.TextField(_("présentation"), blank=True, default="")
    cover = models.ForeignKey("files.File", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    is_active = models.BooleanField(_("active"), default=True)
    # Retrait par la modération (signalement) : la source est aussi désactivée, et seul
    # ``audio.moderer`` peut la réactiver.
    hidden_at = models.DateTimeField(_("retirée par la modération le"), null=True, blank=True)
    created_by = models.ForeignKey("users.BaseUser", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = _("source audio")
        verbose_name_plural = _("sources audio")
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["node", "name"], name="audio_source_node_name_uniq")]

    def __str__(self) -> str:
        return self.name


class Album(BaseModel):
    """Album, messe enregistrée, série d'homélies ou retraite."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(AudioSource, on_delete=models.CASCADE, related_name="albums")
    kind = models.CharField(_("type"), max_length=20, choices=AlbumKind.choices, default=AlbumKind.ALBUM)
    title = models.CharField(_("titre"), max_length=200)
    description = models.TextField(_("description"), blank=True, default="")
    visibility = models.CharField(_("visibilité"), max_length=10, choices=Visibility.choices, default=Visibility.PRIVE)
    cover = models.ForeignKey("files.File", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    recorded_on = models.DateField(_("date d'enregistrement"), null=True, blank=True)
    liturgical_season = models.CharField(
        _("temps liturgique"), max_length=12, choices=LiturgicalSeason.choices, blank=True, default=""
    )
    published_at = models.DateTimeField(_("publié le"), null=True, blank=True)
    hidden_at = models.DateTimeField(_("retiré par la modération le"), null=True, blank=True)
    created_by = models.ForeignKey("users.BaseUser", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = _("album")
        verbose_name_plural = _("albums")
        ordering = ["-recorded_on", "-created_at"]
        indexes = [models.Index(fields=["source", "visibility", "published_at"], name="audio_album_src_vis_pub")]

    def __str__(self) -> str:
        return self.title


class Track(BaseModel):
    """Piste. ``status`` suit l'encodage ; ``version`` augmente à chaque (ré)encodage demandé, et
    ``encoded_version`` désigne le dossier HLS immuable servi (``audio-hls/<id>/<version>/``)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(AudioSource, on_delete=models.CASCADE, related_name="tracks")
    album = models.ForeignKey(Album, null=True, blank=True, on_delete=models.SET_NULL, related_name="tracks")
    position = models.PositiveIntegerField(_("position dans l'album"), default=0)

    # Métadonnées (seules indexées pour la recherche, §5.4).
    title = models.CharField(_("titre"), max_length=250)
    performers = ArrayField(models.CharField(max_length=150), blank=True, default=list, verbose_name=_("interprètes"))
    composer = models.CharField(_("compositeur"), max_length=200, blank=True, default="")
    language = models.CharField(_("langue"), max_length=8, choices=Language.choices, default=Language.FR)
    liturgical_season = models.CharField(
        _("temps liturgique"), max_length=12, choices=LiturgicalSeason.choices, blank=True, default=""
    )
    tags = ArrayField(models.CharField(max_length=60), blank=True, default=list, verbose_name=_("mots-clés"))
    description = models.TextField(_("description"), blank=True, default="")

    # Visibilité propre, et visibilité effective (la plus fermée avec l'album), tenue par les services.
    visibility = models.CharField(_("visibilité"), max_length=10, choices=Visibility.choices, default=Visibility.PUBLIC)
    effective_visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.PRIVE)
    published_at = models.DateTimeField(_("publiée le"), null=True, blank=True)
    hidden_at = models.DateTimeField(_("retirée par la modération le"), null=True, blank=True)

    # Upload et encodage.
    status = models.CharField(_("état"), max_length=12, choices=TrackStatus.choices, default=TrackStatus.BROUILLON)
    failure_reason = models.TextField(_("motif de l'échec"), blank=True, default="")
    raw_file = models.ForeignKey("files.File", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    rights_confirmed_at = models.DateTimeField(_("droits confirmés le"), null=True, blank=True)
    uploaded_by = models.ForeignKey(
        "users.BaseUser", null=True, blank=True, on_delete=models.SET_NULL, related_name="audio_uploads"
    )
    version = models.PositiveIntegerField(_("version demandée"), default=0)
    encoded_version = models.PositiveIntegerField(_("version encodée"), null=True, blank=True)
    encode_attempts = models.PositiveSmallIntegerField(default=0)
    encoding_started_at = models.DateTimeField(null=True, blank=True)
    # Progression de l'encodage en cours (barre de progression du staff), tenue par transcode_track.
    encoding_step = models.CharField(
        _("étape de l'encodage"), max_length=16, choices=EncodingStep.choices, blank=True, default=""
    )
    encoding_percent = models.PositiveSmallIntegerField(_("avancement de l'encodage (%)"), default=0)
    encoded_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.FloatField(_("durée (s)"), null=True, blank=True)
    probe_tags = models.JSONField(_("tags lus par ffprobe"), default=dict, blank=True)
    waveform = models.JSONField(_("forme d'onde (200 pics)"), default=list, blank=True)

    # Compteurs (« les plus écoutés » seulement à l'intérieur d'une source).
    play_count = models.PositiveIntegerField(default=0)
    like_count = models.PositiveIntegerField(default=0)

    # Indexation.
    search_vector = SearchVectorField(null=True, blank=True)

    class Meta:
        verbose_name = _("piste")
        verbose_name_plural = _("pistes")
        ordering = ["album_id", "position", "created_at"]
        indexes = [
            models.Index(fields=["source", "effective_visibility", "published_at"], name="audio_track_src_vis_pub"),
            models.Index(fields=["status", "published_at"], name="audio_track_status_pub"),
            models.Index(fields=["album", "position"], name="audio_track_album_pos"),
            GinIndex(fields=["search_vector"], name="audio_track_search_gin"),
            GinIndex(fields=["title"], name="audio_track_title_trgm", opclasses=["gin_trgm_ops"]),
        ]

    def __str__(self) -> str:
        return self.title


class TrackRendition(BaseModel):
    """Un rendu encodé d'une version de piste (HLS par débit, ou MP3)."""

    track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name="renditions")
    version = models.PositiveIntegerField()
    kind = models.CharField(max_length=12, choices=RenditionKind.choices)
    codec = models.CharField(max_length=40)
    bitrate_kbps = models.PositiveIntegerField()
    channels = models.PositiveSmallIntegerField(default=2)
    path = models.CharField(_("clé dans le stockage"), max_length=300)
    size_bytes = models.BigIntegerField(default=0)

    class Meta:
        verbose_name = _("rendu")
        verbose_name_plural = _("rendus")
        constraints = [
            models.UniqueConstraint(fields=["track", "version", "kind"], name="audio_rendition_uniq"),
        ]

    def __str__(self) -> str:
        return f"{self.track_id} v{self.version} {self.kind}"


class Playlist(BaseModel):
    """Playlist d'un fidèle (``owner``) ou éditoriale d'une source (``source``)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        "users.BaseUser", null=True, blank=True, on_delete=models.CASCADE, related_name="audio_playlists"
    )
    source = models.ForeignKey(
        AudioSource, null=True, blank=True, on_delete=models.CASCADE, related_name="editorial_playlists"
    )
    title = models.CharField(_("titre"), max_length=200)
    description = models.TextField(_("description"), blank=True, default="")
    # Playlist d'un fidèle : « prive » (défaut) ou « public » (partageable). Éditoriale : les trois.
    visibility = models.CharField(_("visibilité"), max_length=10, choices=Visibility.choices, default=Visibility.PRIVE)
    cover = models.ForeignKey("files.File", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("playlist")
        verbose_name_plural = _("playlists")
        ordering = ["-updated_at"]
        constraints = [
            models.CheckConstraint(
                name="audio_playlist_owner_xor_source",
                condition=(Q(owner__isnull=False) & Q(source__isnull=True))
                | (Q(owner__isnull=True) & Q(source__isnull=False)),
            ),
        ]

    def __str__(self) -> str:
        return self.title


class PlaylistItem(models.Model):
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name="items")
    track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name="playlist_items")
    position = models.PositiveIntegerField()
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position"]
        constraints = [models.UniqueConstraint(fields=["playlist", "track"], name="audio_playlist_item_uniq")]
        indexes = [models.Index(fields=["playlist", "position"], name="audio_playlist_item_pos")]


class Like(models.Model):
    user = models.ForeignKey("users.BaseUser", on_delete=models.CASCADE, related_name="audio_likes")
    track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name="likes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "track"], name="audio_like_uniq")]
        indexes = [models.Index(fields=["user", "-created_at"], name="audio_like_user_recent")]


class PlaybackState(models.Model):
    """« Dernière écoute » d'un utilisateur, toutes pistes confondues (une ligne par utilisateur) :
    sert au « Reprendre sur cet appareil ». Dernière écriture gagnante (horodatage client borné)."""

    user = models.OneToOneField("users.BaseUser", on_delete=models.CASCADE, related_name="audio_playback_state")
    track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name="+")
    position_seconds = models.FloatField(default=0)
    device_id = models.CharField(max_length=100, blank=True, default="")
    client_updated_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)


class PlaybackPosition(models.Model):
    """Historique de reprise par piste : où l'utilisateur s'est arrêté dans chaque piste."""

    user = models.ForeignKey("users.BaseUser", on_delete=models.CASCADE, related_name="audio_positions")
    track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name="+")
    position_seconds = models.FloatField(default=0)
    device_id = models.CharField(max_length=100, blank=True, default="")
    client_updated_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "track"], name="audio_position_uniq")]
        indexes = [models.Index(fields=["user", "-client_updated_at"], name="audio_position_user_recent")]


class PlayEvent(models.Model):
    """Événement d'écoute brut. Table **partitionnée par mois** sur ``occurred_at``.

    ``managed = False`` : Django ne sait pas créer une table partitionnée. Elle est créée par la
    migration ``0002_play_event_partitioned`` (SQL brut) ; les partitions mensuelles sont créées
    d'avance par ``audio_play_event_partitions_task`` et purgées après 13 mois. La clé primaire
    réelle est ``(id, occurred_at)`` ; l'idempotence repose sur l'index unique
    ``(client_event_id, occurred_at)`` et ``INSERT … ON CONFLICT DO NOTHING``.
    """

    id = models.BigAutoField(primary_key=True)
    occurred_at = models.DateTimeField()
    received_at = models.DateTimeField()
    client_event_id = models.UUIDField()
    user = models.ForeignKey(
        "users.BaseUser", null=True, blank=True, on_delete=models.DO_NOTHING, db_constraint=False, related_name="+"
    )
    track = models.ForeignKey(Track, on_delete=models.DO_NOTHING, db_constraint=False, related_name="+")
    kind = models.CharField(max_length=10, choices=PlayEventKind.choices)
    position_seconds = models.FloatField(default=0)
    device_id = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        managed = False
        db_table = "audio_play_event"


class TrackNeighbor(models.Model):
    """Voisins précalculés d'une piste (co-écoute ou contenu), top 50 par méthode."""

    track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name="neighbors")
    neighbor = models.ForeignKey(Track, on_delete=models.CASCADE, related_name="+")
    score = models.FloatField()
    method = models.CharField(max_length=10, choices=NeighborMethod.choices)
    computed_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["track", "neighbor", "method"], name="audio_neighbor_uniq"),
        ]
        indexes = [models.Index(fields=["track", "method", "-score"], name="audio_neighbor_rank")]


class UserRecommendation(models.Model):
    """Recommandations précalculées d'un utilisateur (100 au plus), avec leur explication."""

    user = models.ForeignKey("users.BaseUser", on_delete=models.CASCADE, related_name="audio_recommendations")
    track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name="+")
    score = models.FloatField()
    reason = models.CharField(_("raison affichée"), max_length=300)
    reason_track = models.ForeignKey(Track, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    computed_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "track"], name="audio_user_reco_uniq")]
        indexes = [models.Index(fields=["user", "-score"], name="audio_user_reco_rank")]


class ListenerSettings(models.Model):
    """Réglages du fidèle pour la sonothèque. Absent = valeurs par défaut."""

    user = models.OneToOneField("users.BaseUser", on_delete=models.CASCADE, related_name="audio_settings")
    recommendations_enabled = models.BooleanField(_("recommandations personnalisées"), default=True)
    updated_at = models.DateTimeField(auto_now=True)


class TrackReport(BaseModel):
    """Signalement d'un contenu (droits d'auteur, contenu inapproprié) : une piste, un album **ou**
    une source (exactement une cible). Traité par ``audio.moderer`` sur le nœud de la source."""

    track = models.ForeignKey(Track, null=True, blank=True, on_delete=models.CASCADE, related_name="reports")
    album = models.ForeignKey(Album, null=True, blank=True, on_delete=models.CASCADE, related_name="reports")
    source = models.ForeignKey(AudioSource, null=True, blank=True, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey("users.BaseUser", null=True, on_delete=models.SET_NULL, related_name="+")
    reason = models.CharField(max_length=12, choices=ReportReason.choices)
    comment = models.TextField(blank=True, default="")
    status = models.CharField(max_length=8, choices=ReportStatus.choices, default=ReportStatus.OUVERT)
    handled_by = models.ForeignKey("users.BaseUser", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "-created_at"], name="audio_report_status")]
        constraints = [
            models.CheckConstraint(
                name="audio_report_one_target",
                condition=(Q(track__isnull=False) & Q(album__isnull=True) & Q(source__isnull=True))
                | (Q(track__isnull=True) & Q(album__isnull=False) & Q(source__isnull=True))
                | (Q(track__isnull=True) & Q(album__isnull=True) & Q(source__isnull=False)),
            ),
        ]
