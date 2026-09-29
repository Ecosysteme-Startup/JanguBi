"""Sonothèque : couche HTTP uniquement (plan suite V2, §5). Contrat : docs/API-AUDIO.md."""

from typing import Any

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.v1 import V1ApiMixin
from apps.audio import access, selectors, services
from apps.audio.serializers import (
    AudioAlbumDetailSerializer,
    AudioAlbumInputSerializer,
    AudioAlbumListFilterSerializer,
    AudioAlbumSerializer,
    AudioAlbumUpdateInputSerializer,
    AudioEventsInputSerializer,
    AudioEventsResultSerializer,
    AudioForYouSerializer,
    AudioLibrarySerializer,
    AudioLikeOutputSerializer,
    AudioListenerSettingsSerializer,
    AudioLocalUploadInputSerializer,
    AudioPlaybackSerializer,
    AudioPlaybackStateInputSerializer,
    AudioPlaybackStateSerializer,
    AudioPlaybackStateWriteOutputSerializer,
    AudioPlaylistAddInputSerializer,
    AudioPlaylistDetailSerializer,
    AudioPlaylistInputSerializer,
    AudioPlaylistOrderInputSerializer,
    AudioPlaylistSerializer,
    AudioPlaylistUpdateInputSerializer,
    AudioReportDecisionInputSerializer,
    AudioReportInputSerializer,
    AudioReportSerializer,
    AudioSearchOutputSerializer,
    AudioSearchQuerySerializer,
    AudioSourceCreateInputSerializer,
    AudioSourceDetailSerializer,
    AudioSourceListFilterSerializer,
    AudioSourceSerializer,
    AudioSourceUpdateInputSerializer,
    AudioStaffTrackFilterSerializer,
    AudioStaffTrackSerializer,
    AudioTrackSerializer,
    AudioTrackUpdateInputSerializer,
    AudioUploadInputSerializer,
    AudioUploadOutputSerializer,
)
from apps.authentication.keycloak import KeycloakJWTAuthentication
from apps.hierarchy import selectors as hierarchy_selectors

TAG = ["audio"]
_NOT_FOUND = OpenApiResponse(description="Introuvable, ou non visible pour vous")
_FORBIDDEN = OpenApiResponse(description="Capacité audio.publier / audio.moderer requise sur le nœud")


def _body(serializer_class: type[drf_serializers.Serializer], request: Request, **kw: Any) -> dict[str, Any]:
    serializer = serializer_class(data=request.data, **kw)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


def _query(serializer_class: type[drf_serializers.Serializer], request: Request) -> dict[str, Any]:
    serializer = serializer_class(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


class _Api(V1ApiMixin, APIView):
    """Sonothèque paroissiale (contrat : docs/API-AUDIO.md)."""

    authentication_classes = (KeycloakJWTAuthentication,)
    permission_classes: Any = (IsAuthenticated,)


class _PublicApi(_Api):
    """Compte facultatif : un jeton valide ouvre les contenus « paroisse » et « privé » autorisés."""

    permission_classes = (AllowAny,)


# --- Sources ---------------------------------------------------------------------------------


class SourceListCreateApi(_Api):
    def get_permissions(self) -> list[Any]:
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    @extend_schema(
        tags=TAG,
        operation_id="audio_sources_list",
        summary="Sources (paroisses, chorales, mouvements), par ordre alphabétique",
        parameters=[AudioSourceListFilterSerializer],
        responses=AudioSourceSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        f = _query(AudioSourceListFilterSerializer, request)
        sources = selectors.source_list(node_id=f.get("node"), kind=f.get("kind", ""))
        return Response(AudioSourceSerializer(sources, many=True).data)

    @extend_schema(
        tags=TAG,
        operation_id="audio_sources_create",
        summary="Créer une source (audio.publier sur le nœud)",
        request=AudioSourceCreateInputSerializer,
        responses={201: AudioSourceSerializer, 403: _FORBIDDEN},
    )
    def post(self, request: Request) -> Response:
        data = _body(AudioSourceCreateInputSerializer, request)
        node = hierarchy_selectors.node_get(node_id=data.pop("node_id"))
        source = services.source_create(actor=request.user, node=node, **data)
        return Response(AudioSourceSerializer(source).data, status=status.HTTP_201_CREATED)


class SourceDetailApi(_Api):
    def get_permissions(self) -> list[Any]:
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    @extend_schema(
        tags=TAG,
        operation_id="audio_sources_retrieve",
        summary="Page d'une source : albums, playlists, nouveautés, les plus écoutés de la source",
        responses={200: AudioSourceDetailSerializer, 404: _NOT_FOUND},
    )
    def get(self, request: Request, source_id: str) -> Response:
        source = selectors.source_get(source_id=source_id)
        user = request.user
        level = access.access_level(access.membership(user), source.node)

        def build() -> dict[str, Any]:
            return AudioSourceDetailSerializer(
                {
                    "source": source,
                    "albums": selectors.source_albums(user=user, source=source),
                    "playlists": selectors.source_playlists(user=user, source=source),
                    "recent": selectors.source_recent_tracks(user=user, source=source),
                    "most_played": selectors.source_top_tracks(user=user, source=source),
                }
            ).data

        return Response(selectors.catalog_cached(("source", source.pk, level), build))

    @extend_schema(
        tags=TAG,
        operation_id="audio_sources_update",
        summary="Modifier une source",
        request=AudioSourceUpdateInputSerializer,
        responses={200: AudioSourceSerializer, 403: _FORBIDDEN},
    )
    def patch(self, request: Request, source_id: str) -> Response:
        source = selectors.source_get(source_id=source_id)
        data = _body(AudioSourceUpdateInputSerializer, request)
        return Response(AudioSourceSerializer(services.source_update(actor=request.user, source=source, data=data)).data)


# --- Albums ----------------------------------------------------------------------------------


class AlbumListCreateApi(_Api):
    def get_permissions(self) -> list[Any]:
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    @extend_schema(
        tags=TAG,
        operation_id="audio_albums_list",
        summary="Albums visibles (messes, homélies, retraites…)",
        parameters=[AudioAlbumListFilterSerializer],
        responses=AudioAlbumSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        f = _query(AudioAlbumListFilterSerializer, request)
        albums = selectors.album_list(user=request.user, source_id=f.get("source"), kind=f.get("kind", ""))
        return Response(AudioAlbumSerializer(albums[:100], many=True).data)

    @extend_schema(
        tags=TAG,
        operation_id="audio_albums_create",
        summary="Créer un album (brouillon)",
        request=AudioAlbumInputSerializer,
        responses={201: AudioAlbumSerializer, 403: _FORBIDDEN},
    )
    def post(self, request: Request) -> Response:
        data = _body(AudioAlbumInputSerializer, request)
        source = selectors.source_get(source_id=data.pop("source_id"))
        album = services.album_create(actor=request.user, source=source, **data)
        return Response(AudioAlbumSerializer(album).data, status=status.HTTP_201_CREATED)


class AlbumDetailApi(_Api):
    def get_permissions(self) -> list[Any]:
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    @extend_schema(
        tags=TAG,
        operation_id="audio_albums_retrieve",
        summary="Page d'album et ses pistes",
        responses={200: AudioAlbumDetailSerializer, 404: _NOT_FOUND},
    )
    def get(self, request: Request, album_id: str) -> Response:
        album = selectors.album_get(album_id=album_id)
        user = request.user
        selectors.album_require_visible(user=user, album=album)
        level = access.access_level(access.membership(user), album.source.node)

        def build() -> dict[str, Any]:
            return AudioAlbumDetailSerializer(
                {"album": album, "tracks": selectors.album_tracks(user=user, album=album)}
            ).data

        return Response(selectors.catalog_cached(("album", album.pk, level), build))

    @extend_schema(
        tags=TAG,
        operation_id="audio_albums_update",
        summary="Modifier un album (la visibilité s'applique à ses pistes)",
        request=AudioAlbumUpdateInputSerializer,
        responses={200: AudioAlbumSerializer, 403: _FORBIDDEN},
    )
    def patch(self, request: Request, album_id: str) -> Response:
        album = selectors.album_get(album_id=album_id)
        data = _body(AudioAlbumUpdateInputSerializer, request)
        return Response(AudioAlbumSerializer(services.album_update(actor=request.user, album=album, data=data)).data)


class AlbumPublishApi(_Api):
    @extend_schema(
        tags=TAG,
        operation_id="audio_albums_publish",
        summary="Publier l'album et ses pistes prêtes",
        request=None,
        responses={200: AudioAlbumSerializer, 403: _FORBIDDEN},
    )
    def post(self, request: Request, album_id: str) -> Response:
        album = services.album_publish(actor=request.user, album=selectors.album_get(album_id=album_id))
        return Response(AudioAlbumSerializer(album).data)


# --- Pistes ----------------------------------------------------------------------------------


class TrackDetailApi(_Api):
    def get_permissions(self) -> list[Any]:
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    @extend_schema(
        tags=TAG,
        operation_id="audio_tracks_retrieve",
        summary="Fiche d'une piste",
        responses={200: AudioTrackSerializer, 404: _NOT_FOUND},
    )
    def get(self, request: Request, track_id: str) -> Response:
        track = selectors.track_get(track_id=track_id)
        selectors.track_require_visible(user=request.user, track=track)
        return Response(AudioTrackSerializer(track).data)

    @extend_schema(
        tags=TAG,
        operation_id="audio_tracks_update",
        summary="Métadonnées d'une piste (staff de la source)",
        request=AudioTrackUpdateInputSerializer,
        responses={200: AudioStaffTrackSerializer, 403: _FORBIDDEN},
    )
    def patch(self, request: Request, track_id: str) -> Response:
        track = selectors.track_get(track_id=track_id)
        data = _body(AudioTrackUpdateInputSerializer, request)
        if "album_id" in data:
            album_id = data.pop("album_id")
            data["album"] = selectors.album_get(album_id=album_id) if album_id else None
        track = services.track_update(actor=request.user, track=track, data=data)
        return Response(AudioStaffTrackSerializer(track).data)


class TrackPublishApi(_Api):
    @extend_schema(
        tags=TAG,
        operation_id="audio_tracks_publish",
        summary="Publier une piste prête",
        request=None,
        responses={200: AudioStaffTrackSerializer, 409: OpenApiResponse(description="Encodage pas terminé")},
    )
    def post(self, request: Request, track_id: str) -> Response:
        track = services.track_publish(actor=request.user, track=selectors.track_get(track_id=track_id))
        return Response(AudioStaffTrackSerializer(track).data)


class TrackUnpublishApi(_Api):
    @extend_schema(
        tags=TAG,
        operation_id="audio_tracks_unpublish",
        summary="Dépublier une piste",
        request=None,
        responses={200: AudioStaffTrackSerializer},
    )
    def post(self, request: Request, track_id: str) -> Response:
        track = services.track_unpublish(actor=request.user, track=selectors.track_get(track_id=track_id))
        return Response(AudioStaffTrackSerializer(track).data)


class TrackReencodeApi(_Api):
    @extend_schema(
        tags=TAG,
        operation_id="audio_tracks_reencode",
        summary="Réencoder depuis le fichier source (nouvelle version)",
        request=None,
        responses={202: AudioStaffTrackSerializer},
    )
    def post(self, request: Request, track_id: str) -> Response:
        track = services.track_reencode(actor=request.user, track=selectors.track_get(track_id=track_id))
        return Response(AudioStaffTrackSerializer(track).data, status=status.HTTP_202_ACCEPTED)


class TrackPlaybackApi(_PublicApi):
    @extend_schema(
        tags=TAG,
        operation_id="audio_tracks_playback",
        summary="Lecture : droit d'écoute, URL signée du master.m3u8, position de reprise, forme d'onde",
        request=None,
        responses={
            200: AudioPlaybackSerializer,
            404: _NOT_FOUND,
            409: OpenApiResponse(description="Piste pas encore prête"),
        },
    )
    def post(self, request: Request, track_id: str) -> Response:
        track = selectors.track_get(track_id=track_id)
        return Response(AudioPlaybackSerializer(selectors.playback_info(user=request.user, track=track)).data)


class TrackLikeApi(_Api):
    @extend_schema(
        tags=TAG, operation_id="audio_tracks_like", summary="Aimer une piste", request=None,
        responses=AudioLikeOutputSerializer,
    )  # fmt: skip
    def put(self, request: Request, track_id: str) -> Response:
        services.like_add(user=request.user, track=selectors.track_get(track_id=track_id))
        return Response({"liked": True})

    @extend_schema(
        tags=TAG, operation_id="audio_tracks_unlike", summary="Ne plus aimer une piste", request=None,
        responses=AudioLikeOutputSerializer,
    )  # fmt: skip
    def delete(self, request: Request, track_id: str) -> Response:
        services.like_remove(user=request.user, track=selectors.track_get(track_id=track_id))
        return Response({"liked": False})


class TrackNextApi(_PublicApi):
    @extend_schema(
        tags=TAG,
        operation_id="audio_tracks_next",
        summary="À écouter ensuite (voisins précalculés, filtrés par droits)",
        responses={200: AudioTrackSerializer(many=True), 404: _NOT_FOUND},
    )
    def get(self, request: Request, track_id: str) -> Response:
        track = selectors.track_get(track_id=track_id)
        return Response(AudioTrackSerializer(selectors.next_tracks(user=request.user, track=track), many=True).data)


class TrackReportApi(_Api):
    @extend_schema(
        tags=TAG,
        operation_id="audio_tracks_report",
        summary="Signaler une piste (droits d'auteur, contenu inapproprié, son)",
        request=AudioReportInputSerializer,
        responses={201: AudioReportSerializer},
    )
    def post(self, request: Request, track_id: str) -> Response:
        data = _body(AudioReportInputSerializer, request)
        report = services.report_create(
            user=request.user, track=selectors.track_get(track_id=track_id), reason=data["motif"], comment=data["comment"]
        )
        return Response(AudioReportSerializer(report).data, status=status.HTTP_201_CREATED)


# --- Upload ----------------------------------------------------------------------------------


class UploadStartApi(_Api):
    @extend_schema(
        tags=TAG,
        operation_id="audio_uploads_create",
        summary="Démarrer un envoi : POST présigné vers audio-raw/ (500 Mo, mp3/m4a/aac/wav/flac/ogg/opus)",
        request=AudioUploadInputSerializer,
        responses={201: AudioUploadOutputSerializer, 400: OpenApiResponse(description="Droits non confirmés, format ou taille"), 403: _FORBIDDEN},
    )
    def post(self, request: Request) -> Response:
        data = _body(AudioUploadInputSerializer, request)
        source = selectors.source_get(source_id=data.pop("source_id"))
        album_id = data.pop("album_id", None)
        album = selectors.album_get(album_id=album_id) if album_id else None
        result = services.upload_start(actor=request.user, source=source, album=album, **data)
        return Response(AudioUploadOutputSerializer(result).data, status=status.HTTP_201_CREATED)


class UploadDetailApi(_Api):
    @extend_schema(
        tags=TAG,
        operation_id="audio_uploads_retrieve",
        summary="État d'un envoi (brouillon, en_file, encodage, pret, echec + motif)",
        responses={200: AudioStaffTrackSerializer, 404: _NOT_FOUND},
    )
    def get(self, request: Request, track_id: str) -> Response:
        track = selectors.track_get(track_id=track_id)
        if track.uploaded_by_id != request.user.pk:
            access.require_publish(request.user, track.source.node)
        return Response(AudioStaffTrackSerializer(track).data)


class UploadLocalApi(_Api):
    @extend_schema(
        tags=TAG,
        operation_id="audio_uploads_local",
        summary="Envoi du fichier en développement (stockage local, sans S3)",
        request={"multipart/form-data": AudioLocalUploadInputSerializer},
        responses={200: AudioStaffTrackSerializer},
    )
    def post(self, request: Request, track_id: str) -> Response:
        data = _body(AudioLocalUploadInputSerializer, request)
        track = services.upload_local(actor=request.user, track=selectors.track_get(track_id=track_id), file_obj=data["file"])
        return Response(AudioStaffTrackSerializer(track).data)


class UploadFinishApi(_Api):
    @extend_schema(
        tags=TAG,
        operation_id="audio_uploads_finish",
        summary="Fin de l'envoi : la piste passe « en_file » et part à l'encodage (file media)",
        request=None,
        responses={202: AudioStaffTrackSerializer, 400: OpenApiResponse(description="Fichier absent ou trop gros")},
    )
    def post(self, request: Request, track_id: str) -> Response:
        track = services.upload_finish(actor=request.user, track=selectors.track_get(track_id=track_id))
        return Response(AudioStaffTrackSerializer(track).data, status=status.HTTP_202_ACCEPTED)


# --- Reprise et synchronisation --------------------------------------------------------------


class PlaybackStateApi(_Api):
    @extend_schema(
        tags=TAG,
        operation_id="audio_playback_state_get",
        summary="Dernière écoute (« Reprendre sur cet appareil »)",
        responses={200: AudioPlaybackStateSerializer, 204: OpenApiResponse(description="Aucune écoute")},
    )
    def get(self, request: Request) -> Response:
        state = selectors.playback_state_get(user=request.user)
        if state is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(AudioPlaybackStateSerializer(state).data)

    @extend_schema(
        tags=TAG,
        operation_id="audio_playback_state_put",
        summary="Position courante (toutes les 15 s, à la pause, à la fermeture) ; dernière écriture gagnante",
        request=AudioPlaybackStateInputSerializer,
        responses=AudioPlaybackStateWriteOutputSerializer,
    )
    def put(self, request: Request) -> Response:
        data = _body(AudioPlaybackStateInputSerializer, request)
        track = selectors.track_get(track_id=data.pop("track_id"))
        state, applied = services.playback_state_update(user=request.user, track=track, **data)
        return Response(AudioPlaybackStateWriteOutputSerializer({"applied": applied, "state": state}).data)


# --- Recherche, bibliothèque, événements, recommandations --------------------------------------


class SearchApi(_PublicApi):
    @extend_schema(
        tags=TAG,
        operation_id="audio_search",
        summary="Recherche (plein texte français sans accents + fautes de frappe), pagination par curseur",
        parameters=[AudioSearchQuerySerializer],
        responses=AudioSearchOutputSerializer,
    )
    def get(self, request: Request) -> Response:
        f = _query(AudioSearchQuerySerializer, request)
        result = selectors.track_search(user=request.user, q=f["q"], cursor=f["cursor"], limit=f["limit"])
        return Response(AudioSearchOutputSerializer(result).data)


class LibraryApi(_Api):
    @extend_schema(
        tags=TAG,
        operation_id="audio_library",
        summary="Ma bibliothèque : pistes aimées, mes playlists, écoutes en cours",
        responses=AudioLibrarySerializer,
    )
    def get(self, request: Request) -> Response:
        return Response(AudioLibrarySerializer(selectors.library(user=request.user)).data)


class EventsApi(_PublicApi):
    @extend_schema(
        tags=TAG,
        operation_id="audio_events_create",
        summary="Événements d'écoute par lot (100 au plus), idempotents par client_event_id",
        request=AudioEventsInputSerializer,
        responses={202: AudioEventsResultSerializer},
    )
    def post(self, request: Request) -> Response:
        data = _body(AudioEventsInputSerializer, request)
        result = services.play_events_ingest(user=request.user, events=data["events"])
        return Response(result, status=status.HTTP_202_ACCEPTED)


class ForYouApi(_Api):
    @extend_schema(
        tags=TAG,
        operation_id="audio_for_you",
        summary="Pour vous : recommandations précalculées, avec leur explication",
        responses=AudioForYouSerializer,
    )
    def get(self, request: Request) -> Response:
        return Response(AudioForYouSerializer(selectors.recommendations_for(user=request.user)).data)


class ListenerSettingsApi(_Api):
    @extend_schema(
        tags=TAG, operation_id="audio_settings_get", summary="Réglages de la sonothèque",
        responses=AudioListenerSettingsSerializer,
    )  # fmt: skip
    def get(self, request: Request) -> Response:
        return Response(AudioListenerSettingsSerializer(selectors.listener_settings_get(user=request.user)).data)

    @extend_schema(
        tags=TAG,
        operation_id="audio_settings_put",
        summary="Activer ou désactiver les recommandations personnalisées",
        request=AudioListenerSettingsSerializer,
        responses=AudioListenerSettingsSerializer,
    )
    def put(self, request: Request) -> Response:
        data = _body(AudioListenerSettingsSerializer, request)
        prefs = services.listener_settings_update(user=request.user, **data)
        return Response(AudioListenerSettingsSerializer(prefs).data)


# --- Playlists -------------------------------------------------------------------------------


class PlaylistListCreateApi(_Api):
    @extend_schema(
        tags=TAG, operation_id="audio_playlists_list", summary="Mes playlists",
        responses=AudioPlaylistSerializer(many=True),
    )  # fmt: skip
    def get(self, request: Request) -> Response:
        return Response(AudioPlaylistSerializer(selectors.playlists_of(user=request.user), many=True).data)

    @extend_schema(
        tags=TAG,
        operation_id="audio_playlists_create",
        summary="Créer une playlist (personnelle, ou éditoriale avec source_id)",
        request=AudioPlaylistInputSerializer,
        responses={201: AudioPlaylistSerializer},
    )
    def post(self, request: Request) -> Response:
        data = _body(AudioPlaylistInputSerializer, request)
        source_id = data.pop("source_id", None)
        source = selectors.source_get(source_id=source_id) if source_id else None
        playlist = services.playlist_create(actor=request.user, source=source, **data)
        return Response(AudioPlaylistSerializer(playlist).data, status=status.HTTP_201_CREATED)


class PlaylistDetailApi(_Api):
    def get_permissions(self) -> list[Any]:
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    @extend_schema(
        tags=TAG, operation_id="audio_playlists_retrieve", summary="Playlist et ses pistes (filtrées par droits)",
        responses={200: AudioPlaylistDetailSerializer, 404: _NOT_FOUND},
    )  # fmt: skip
    def get(self, request: Request, playlist_id: str) -> Response:
        playlist = selectors.playlist_get(playlist_id=playlist_id)
        if not access.can_view_playlist(request.user, playlist):
            return Response(status=status.HTTP_404_NOT_FOUND)
        tracks = selectors.playlist_tracks(user=request.user, playlist=playlist)
        return Response(AudioPlaylistDetailSerializer({"playlist": playlist, "tracks": tracks}).data)

    @extend_schema(
        tags=TAG, operation_id="audio_playlists_update", summary="Modifier une playlist",
        request=AudioPlaylistUpdateInputSerializer, responses=AudioPlaylistSerializer,
    )  # fmt: skip
    def patch(self, request: Request, playlist_id: str) -> Response:
        playlist = selectors.playlist_get(playlist_id=playlist_id)
        data = _body(AudioPlaylistUpdateInputSerializer, request)
        playlist = services.playlist_update(actor=request.user, playlist=playlist, data=data)
        return Response(AudioPlaylistSerializer(playlist).data)

    @extend_schema(
        tags=TAG, operation_id="audio_playlists_delete", summary="Supprimer une playlist", request=None,
        responses={204: None},
    )  # fmt: skip
    def delete(self, request: Request, playlist_id: str) -> Response:
        services.playlist_delete(actor=request.user, playlist=selectors.playlist_get(playlist_id=playlist_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlaylistTracksApi(_Api):
    @extend_schema(
        tags=TAG, operation_id="audio_playlists_add_track", summary="Ajouter une piste à la fin",
        request=AudioPlaylistAddInputSerializer, responses={201: AudioPlaylistSerializer},
    )  # fmt: skip
    def post(self, request: Request, playlist_id: str) -> Response:
        playlist = selectors.playlist_get(playlist_id=playlist_id)
        data = _body(AudioPlaylistAddInputSerializer, request)
        track = selectors.track_get(track_id=data["track_id"])
        services.playlist_add_track(actor=request.user, playlist=playlist, track=track)
        return Response(AudioPlaylistSerializer(playlist).data, status=status.HTTP_201_CREATED)


class PlaylistTrackRemoveApi(_Api):
    @extend_schema(
        tags=TAG, operation_id="audio_playlists_remove_track", summary="Retirer une piste", request=None,
        responses={204: None},
    )  # fmt: skip
    def delete(self, request: Request, playlist_id: str, track_id: str) -> Response:
        playlist = selectors.playlist_get(playlist_id=playlist_id)
        services.playlist_remove_track(actor=request.user, playlist=playlist, track=selectors.track_get(track_id=track_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlaylistOrderApi(_Api):
    @extend_schema(
        tags=TAG, operation_id="audio_playlists_reorder", summary="Réordonner (liste complète des pistes)",
        request=AudioPlaylistOrderInputSerializer, responses=AudioPlaylistDetailSerializer,
    )  # fmt: skip
    def put(self, request: Request, playlist_id: str) -> Response:
        playlist = selectors.playlist_get(playlist_id=playlist_id)
        data = _body(AudioPlaylistOrderInputSerializer, request)
        playlist = services.playlist_reorder(actor=request.user, playlist=playlist, track_ids=data["track_ids"])
        tracks = selectors.playlist_tracks(user=request.user, playlist=playlist)
        return Response(AudioPlaylistDetailSerializer({"playlist": playlist, "tracks": tracks}).data)


# --- Staff et modération ---------------------------------------------------------------------


class StaffSourcesApi(_Api):
    @extend_schema(
        tags=TAG, operation_id="audio_staff_sources", summary="Sources où je peux publier",
        responses=AudioSourceSerializer(many=True),
    )  # fmt: skip
    def get(self, request: Request) -> Response:
        return Response(AudioSourceSerializer(selectors.staff_sources(user=request.user), many=True).data)


class StaffTracksApi(_Api):
    @extend_schema(
        tags=TAG,
        operation_id="audio_staff_tracks",
        summary="Toutes les pistes d'une source, avec l'état de l'encodage",
        parameters=[AudioStaffTrackFilterSerializer],
        responses={200: AudioStaffTrackSerializer(many=True), 403: _FORBIDDEN},
    )
    def get(self, request: Request) -> Response:
        f = _query(AudioStaffTrackFilterSerializer, request)
        source = selectors.source_get(source_id=f["source"])
        tracks = selectors.staff_tracks(user=request.user, source=source, status=f.get("status", ""))
        return Response(AudioStaffTrackSerializer(tracks[:200], many=True).data)


class ReportListApi(_Api):
    @extend_schema(
        tags=TAG, operation_id="audio_reports_list", summary="Signalements ouverts (audio.moderer)",
        responses=AudioReportSerializer(many=True),
    )  # fmt: skip
    def get(self, request: Request) -> Response:
        return Response(AudioReportSerializer(selectors.reports_open(user=request.user)[:200], many=True).data)


class ReportHandleApi(_Api):
    @extend_schema(
        tags=TAG, operation_id="audio_reports_handle", summary="Traiter un signalement : retirer ou classer sans suite",
        request=AudioReportDecisionInputSerializer, responses={200: AudioReportSerializer, 403: _FORBIDDEN},
    )  # fmt: skip
    def post(self, request: Request, report_id: int) -> Response:
        data = _body(AudioReportDecisionInputSerializer, request)
        report = services.report_handle(
            actor=request.user, report=selectors.report_get(report_id=report_id), decision=data["resolution"]
        )
        return Response(AudioReportSerializer(report).data)

