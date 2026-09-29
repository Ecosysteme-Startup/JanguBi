"""Sonothèque (plan suite V2, §5) : schéma initial.

Les extensions sont créées ici si besoin (``IF NOT EXISTS``) ; le retour arrière ne les supprime
pas, d'autres apps s'en servent (pg_trgm et vector pour la Bible). ``PlayEvent`` est déclaré
``managed=False`` : sa table partitionnée est créée par ``0002_play_event_partitioned``.
"""

import django.contrib.postgres.fields
import django.contrib.postgres.indexes
import django.contrib.postgres.search
import django.db.models.deletion
import django.utils.timezone
import pgvector.django.indexes
import pgvector.django.vector
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("files", "0002_initial"),
        ("hierarchy", "0010_audio_capacites"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunSQL(
            [
                "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
                "CREATE EXTENSION IF NOT EXISTS unaccent;",
                "CREATE EXTENSION IF NOT EXISTS vector;",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.CreateModel(
            name="PlayEvent",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("occurred_at", models.DateTimeField()),
                ("received_at", models.DateTimeField()),
                ("client_event_id", models.UUIDField()),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("start", "Début d'écoute"),
                            ("progress", "Progression"),
                            ("complete", "Écoute complète"),
                            ("skip", "Passée"),
                            ("like", "Aimée"),
                        ],
                        max_length=10,
                    ),
                ),
                ("position_seconds", models.FloatField(default=0)),
                ("device_id", models.CharField(blank=True, default="", max_length=100)),
            ],
            options={
                "db_table": "audio_play_event",
                "managed": False,
            },
        ),
        migrations.CreateModel(
            name="AudioSource",
            fields=[
                (
                    "created_at",
                    models.DateTimeField(
                        db_index=True, default=django.utils.timezone.now
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("paroisse", "Paroisse"),
                            ("chorale", "Chorale"),
                            ("mouvement", "Mouvement"),
                        ],
                        default="paroisse",
                        max_length=20,
                        verbose_name="type",
                    ),
                ),
                ("name", models.CharField(max_length=200, verbose_name="nom")),
                (
                    "description",
                    models.TextField(
                        blank=True, default="", verbose_name="présentation"
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="active")),
                (
                    "cover",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="files.file",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "node",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="audio_sources",
                        to="hierarchy.node",
                    ),
                ),
            ],
            options={
                "verbose_name": "source audio",
                "verbose_name_plural": "sources audio",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="Album",
            fields=[
                (
                    "created_at",
                    models.DateTimeField(
                        db_index=True, default=django.utils.timezone.now
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("album", "Album"),
                            ("messe", "Messe enregistrée"),
                            ("homelies", "Série d'homélies"),
                            ("retraite", "Retraite"),
                        ],
                        default="album",
                        max_length=20,
                        verbose_name="type",
                    ),
                ),
                ("title", models.CharField(max_length=200, verbose_name="titre")),
                (
                    "description",
                    models.TextField(
                        blank=True, default="", verbose_name="description"
                    ),
                ),
                (
                    "visibility",
                    models.CharField(
                        choices=[
                            ("public", "Public"),
                            ("paroisse", "Membres de la paroisse"),
                            ("prive", "Privé (brouillon du staff)"),
                        ],
                        default="prive",
                        max_length=10,
                        verbose_name="visibilité",
                    ),
                ),
                (
                    "recorded_on",
                    models.DateField(
                        blank=True, null=True, verbose_name="date d'enregistrement"
                    ),
                ),
                (
                    "liturgical_season",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("avent", "Temps de l'Avent"),
                            ("noel", "Temps de Noël"),
                            ("careme", "Temps du Carême"),
                            ("triduum", "Triduum pascal"),
                            ("paques", "Temps pascal"),
                            ("ordinaire", "Temps ordinaire"),
                        ],
                        default="",
                        max_length=12,
                        verbose_name="temps liturgique",
                    ),
                ),
                (
                    "published_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="publié le"
                    ),
                ),
                (
                    "cover",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="files.file",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="albums",
                        to="audio.audiosource",
                    ),
                ),
            ],
            options={
                "verbose_name": "album",
                "verbose_name_plural": "albums",
                "ordering": ["-recorded_on", "-created_at"],
            },
        ),
        migrations.CreateModel(
            name="ListenerSettings",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "recommendations_enabled",
                    models.BooleanField(
                        default=True, verbose_name="recommandations personnalisées"
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="audio_settings",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Playlist",
            fields=[
                (
                    "created_at",
                    models.DateTimeField(
                        db_index=True, default=django.utils.timezone.now
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("title", models.CharField(max_length=200, verbose_name="titre")),
                (
                    "description",
                    models.TextField(
                        blank=True, default="", verbose_name="description"
                    ),
                ),
                (
                    "visibility",
                    models.CharField(
                        choices=[
                            ("public", "Public"),
                            ("paroisse", "Membres de la paroisse"),
                            ("prive", "Privé (brouillon du staff)"),
                        ],
                        default="prive",
                        max_length=10,
                        verbose_name="visibilité",
                    ),
                ),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                (
                    "cover",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="files.file",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="audio_playlists",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "source",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="editorial_playlists",
                        to="audio.audiosource",
                    ),
                ),
            ],
            options={
                "verbose_name": "playlist",
                "verbose_name_plural": "playlists",
                "ordering": ["-updated_at"],
            },
        ),
        migrations.CreateModel(
            name="Track",
            fields=[
                (
                    "created_at",
                    models.DateTimeField(
                        db_index=True, default=django.utils.timezone.now
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "position",
                    models.PositiveIntegerField(
                        default=0, verbose_name="position dans l'album"
                    ),
                ),
                ("title", models.CharField(max_length=250, verbose_name="titre")),
                (
                    "performers",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=150),
                        blank=True,
                        default=list,
                        size=None,
                        verbose_name="interprètes",
                    ),
                ),
                (
                    "composer",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=200,
                        verbose_name="compositeur",
                    ),
                ),
                (
                    "language",
                    models.CharField(
                        choices=[
                            ("fr", "Français"),
                            ("wo", "Wolof"),
                            ("la", "Latin"),
                            ("srr", "Sérère"),
                            ("dyo", "Diola"),
                            ("en", "Anglais"),
                            ("autre", "Autre"),
                        ],
                        default="fr",
                        max_length=8,
                        verbose_name="langue",
                    ),
                ),
                (
                    "liturgical_season",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("avent", "Temps de l'Avent"),
                            ("noel", "Temps de Noël"),
                            ("careme", "Temps du Carême"),
                            ("triduum", "Triduum pascal"),
                            ("paques", "Temps pascal"),
                            ("ordinaire", "Temps ordinaire"),
                        ],
                        default="",
                        max_length=12,
                        verbose_name="temps liturgique",
                    ),
                ),
                (
                    "tags",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=60),
                        blank=True,
                        default=list,
                        size=None,
                        verbose_name="mots-clés",
                    ),
                ),
                (
                    "description",
                    models.TextField(
                        blank=True, default="", verbose_name="description"
                    ),
                ),
                (
                    "visibility",
                    models.CharField(
                        choices=[
                            ("public", "Public"),
                            ("paroisse", "Membres de la paroisse"),
                            ("prive", "Privé (brouillon du staff)"),
                        ],
                        default="public",
                        max_length=10,
                        verbose_name="visibilité",
                    ),
                ),
                (
                    "effective_visibility",
                    models.CharField(
                        choices=[
                            ("public", "Public"),
                            ("paroisse", "Membres de la paroisse"),
                            ("prive", "Privé (brouillon du staff)"),
                        ],
                        default="prive",
                        max_length=10,
                    ),
                ),
                (
                    "published_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="publiée le"
                    ),
                ),
                (
                    "hidden_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="retirée par la modération le",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("brouillon", "Brouillon (upload en cours)"),
                            ("en_file", "En file d'encodage"),
                            ("encodage", "Encodage en cours"),
                            ("pret", "Prêt"),
                            ("echec", "Échec de l'encodage"),
                        ],
                        default="brouillon",
                        max_length=12,
                        verbose_name="état",
                    ),
                ),
                (
                    "failure_reason",
                    models.TextField(
                        blank=True, default="", verbose_name="motif de l'échec"
                    ),
                ),
                (
                    "rights_confirmed_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="droits confirmés le"
                    ),
                ),
                (
                    "version",
                    models.PositiveIntegerField(
                        default=0, verbose_name="version demandée"
                    ),
                ),
                (
                    "encoded_version",
                    models.PositiveIntegerField(
                        blank=True, null=True, verbose_name="version encodée"
                    ),
                ),
                ("encode_attempts", models.PositiveSmallIntegerField(default=0)),
                ("encoding_started_at", models.DateTimeField(blank=True, null=True)),
                ("encoded_at", models.DateTimeField(blank=True, null=True)),
                (
                    "duration_seconds",
                    models.FloatField(blank=True, null=True, verbose_name="durée (s)"),
                ),
                (
                    "probe_tags",
                    models.JSONField(
                        blank=True, default=dict, verbose_name="tags lus par ffprobe"
                    ),
                ),
                (
                    "waveform",
                    models.JSONField(
                        blank=True, default=list, verbose_name="forme d'onde (200 pics)"
                    ),
                ),
                ("play_count", models.PositiveIntegerField(default=0)),
                ("like_count", models.PositiveIntegerField(default=0)),
                (
                    "search_vector",
                    django.contrib.postgres.search.SearchVectorField(
                        blank=True, null=True
                    ),
                ),
                (
                    "embedding",
                    pgvector.django.vector.VectorField(
                        blank=True, dimensions=768, null=True
                    ),
                ),
                (
                    "embedding_text_hash",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                (
                    "album",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tracks",
                        to="audio.album",
                    ),
                ),
                (
                    "raw_file",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="files.file",
                    ),
                ),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tracks",
                        to="audio.audiosource",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="audio_uploads",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "piste",
                "verbose_name_plural": "pistes",
                "ordering": ["album_id", "position", "created_at"],
            },
        ),
        migrations.CreateModel(
            name="PlaylistItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("position", models.PositiveIntegerField()),
                ("added_at", models.DateTimeField(auto_now_add=True)),
                (
                    "playlist",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="audio.playlist",
                    ),
                ),
                (
                    "track",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="playlist_items",
                        to="audio.track",
                    ),
                ),
            ],
            options={
                "ordering": ["position"],
            },
        ),
        migrations.CreateModel(
            name="PlaybackState",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("position_seconds", models.FloatField(default=0)),
                ("device_id", models.CharField(blank=True, default="", max_length=100)),
                ("client_updated_at", models.DateTimeField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="audio_playback_state",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "track",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="audio.track",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="PlaybackPosition",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("position_seconds", models.FloatField(default=0)),
                ("device_id", models.CharField(blank=True, default="", max_length=100)),
                ("client_updated_at", models.DateTimeField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="audio_positions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "track",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="audio.track",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Like",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="audio_likes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "track",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="likes",
                        to="audio.track",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="TrackNeighbor",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("score", models.FloatField()),
                (
                    "method",
                    models.CharField(
                        choices=[
                            ("coecoute", "Co-écoute"),
                            ("contenu", "Contenu (métadonnées)"),
                        ],
                        max_length=10,
                    ),
                ),
                ("computed_at", models.DateTimeField()),
                (
                    "neighbor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="audio.track",
                    ),
                ),
                (
                    "track",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="neighbors",
                        to="audio.track",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="TrackRendition",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        db_index=True, default=django.utils.timezone.now
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("version", models.PositiveIntegerField()),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("hls_bas", "HLS bas débit (2G/3G)"),
                            ("hls_moyen", "HLS 64 kb/s"),
                            ("hls_haut", "HLS 128 kb/s"),
                            ("mp3", "MP3 128 kb/s (hors ligne)"),
                        ],
                        max_length=12,
                    ),
                ),
                ("codec", models.CharField(max_length=40)),
                ("bitrate_kbps", models.PositiveIntegerField()),
                ("channels", models.PositiveSmallIntegerField(default=2)),
                (
                    "path",
                    models.CharField(
                        max_length=300, verbose_name="clé dans le stockage"
                    ),
                ),
                ("size_bytes", models.BigIntegerField(default=0)),
                (
                    "track",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="renditions",
                        to="audio.track",
                    ),
                ),
            ],
            options={
                "verbose_name": "rendu",
                "verbose_name_plural": "rendus",
            },
        ),
        migrations.CreateModel(
            name="TrackReport",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        db_index=True, default=django.utils.timezone.now
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "reason",
                    models.CharField(
                        choices=[
                            ("droits", "Droits d'auteur"),
                            ("inapproprie", "Contenu inapproprié"),
                            ("qualite", "Problème de son"),
                            ("autre", "Autre"),
                        ],
                        max_length=12,
                    ),
                ),
                ("comment", models.TextField(blank=True, default="")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("ouvert", "Ouvert"),
                            ("retire", "Contenu retiré"),
                            ("rejete", "Sans suite"),
                        ],
                        default="ouvert",
                        max_length=8,
                    ),
                ),
                ("handled_at", models.DateTimeField(blank=True, null=True)),
                (
                    "handled_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "reporter",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "track",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reports",
                        to="audio.track",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="UserRecommendation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("score", models.FloatField()),
                (
                    "reason",
                    models.CharField(max_length=300, verbose_name="raison affichée"),
                ),
                ("computed_at", models.DateTimeField()),
                (
                    "reason_track",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="audio.track",
                    ),
                ),
                (
                    "track",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="audio.track",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="audio_recommendations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="audiosource",
            constraint=models.UniqueConstraint(
                fields=("node", "name"), name="audio_source_node_name_uniq"
            ),
        ),
        migrations.AddIndex(
            model_name="album",
            index=models.Index(
                fields=["source", "visibility", "published_at"],
                name="audio_album_src_vis_pub",
            ),
        ),
        migrations.AddConstraint(
            model_name="playlist",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("owner__isnull", False), ("source__isnull", True)),
                    models.Q(("owner__isnull", True), ("source__isnull", False)),
                    _connector="OR",
                ),
                name="audio_playlist_owner_xor_source",
            ),
        ),
        migrations.AddIndex(
            model_name="track",
            index=models.Index(
                fields=["source", "effective_visibility", "published_at"],
                name="audio_track_src_vis_pub",
            ),
        ),
        migrations.AddIndex(
            model_name="track",
            index=models.Index(
                fields=["status", "published_at"], name="audio_track_status_pub"
            ),
        ),
        migrations.AddIndex(
            model_name="track",
            index=models.Index(
                fields=["album", "position"], name="audio_track_album_pos"
            ),
        ),
        migrations.AddIndex(
            model_name="track",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["search_vector"], name="audio_track_search_gin"
            ),
        ),
        migrations.AddIndex(
            model_name="track",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["title"],
                name="audio_track_title_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ),
        migrations.AddIndex(
            model_name="track",
            index=pgvector.django.indexes.HnswIndex(
                ef_construction=64,
                fields=["embedding"],
                m=16,
                name="audio_track_embedding_hnsw",
                opclasses=["vector_cosine_ops"],
            ),
        ),
        migrations.AddIndex(
            model_name="playlistitem",
            index=models.Index(
                fields=["playlist", "position"], name="audio_playlist_item_pos"
            ),
        ),
        migrations.AddConstraint(
            model_name="playlistitem",
            constraint=models.UniqueConstraint(
                fields=("playlist", "track"), name="audio_playlist_item_uniq"
            ),
        ),
        migrations.AddIndex(
            model_name="playbackposition",
            index=models.Index(
                fields=["user", "-client_updated_at"], name="audio_position_user_recent"
            ),
        ),
        migrations.AddConstraint(
            model_name="playbackposition",
            constraint=models.UniqueConstraint(
                fields=("user", "track"), name="audio_position_uniq"
            ),
        ),
        migrations.AddIndex(
            model_name="like",
            index=models.Index(
                fields=["user", "-created_at"], name="audio_like_user_recent"
            ),
        ),
        migrations.AddConstraint(
            model_name="like",
            constraint=models.UniqueConstraint(
                fields=("user", "track"), name="audio_like_uniq"
            ),
        ),
        migrations.AddIndex(
            model_name="trackneighbor",
            index=models.Index(
                fields=["track", "method", "-score"], name="audio_neighbor_rank"
            ),
        ),
        migrations.AddConstraint(
            model_name="trackneighbor",
            constraint=models.UniqueConstraint(
                fields=("track", "neighbor", "method"), name="audio_neighbor_uniq"
            ),
        ),
        migrations.AddConstraint(
            model_name="trackrendition",
            constraint=models.UniqueConstraint(
                fields=("track", "version", "kind"), name="audio_rendition_uniq"
            ),
        ),
        migrations.AddIndex(
            model_name="trackreport",
            index=models.Index(
                fields=["status", "-created_at"], name="audio_report_status"
            ),
        ),
        migrations.AddIndex(
            model_name="userrecommendation",
            index=models.Index(fields=["user", "-score"], name="audio_user_reco_rank"),
        ),
        migrations.AddConstraint(
            model_name="userrecommendation",
            constraint=models.UniqueConstraint(
                fields=("user", "track"), name="audio_user_reco_uniq"
            ),
        ),
    ]
