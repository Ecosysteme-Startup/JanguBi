from django.db import transaction
from django.urls import path

from apps.audio import apis
from apps.realtime.apis import AudioUploadFluxApi

urlpatterns = [
    path("sources/", apis.SourceListCreateApi.as_view(), name="sources"),
    path("sources/<uuid:source_id>/", apis.SourceDetailApi.as_view(), name="source-detail"),
    path("sources/<uuid:source_id>/signaler/", apis.SourceReportApi.as_view(), name="source-report"),
    path("albums/", apis.AlbumListCreateApi.as_view(), name="albums"),
    path("albums/<uuid:album_id>/", apis.AlbumDetailApi.as_view(), name="album-detail"),
    path("albums/<uuid:album_id>/publier/", apis.AlbumPublishApi.as_view(), name="album-publish"),
    path("albums/<uuid:album_id>/signaler/", apis.AlbumReportApi.as_view(), name="album-report"),
    path("pistes/<uuid:track_id>/", apis.TrackDetailApi.as_view(), name="track-detail"),
    path("pistes/<uuid:track_id>/publier/", apis.TrackPublishApi.as_view(), name="track-publish"),
    path("pistes/<uuid:track_id>/depublier/", apis.TrackUnpublishApi.as_view(), name="track-unpublish"),
    path("pistes/<uuid:track_id>/reencoder/", apis.TrackReencodeApi.as_view(), name="track-reencode"),
    path("pistes/<uuid:track_id>/lecture/", apis.TrackPlaybackApi.as_view(), name="track-playback"),
    path("pistes/<uuid:track_id>/telechargement/", apis.TrackDownloadApi.as_view(), name="track-download"),
    path("telechargements/verifier/", apis.OfflineVerifyApi.as_view(), name="downloads-verify"),
    path("pistes/<uuid:track_id>/like/", apis.TrackLikeApi.as_view(), name="track-like"),
    path("pistes/<uuid:track_id>/ensuite/", apis.TrackNextApi.as_view(), name="track-next"),
    path("pistes/<uuid:track_id>/signaler/", apis.TrackReportApi.as_view(), name="track-report"),
    path("uploads/", apis.UploadStartApi.as_view(), name="uploads"),
    path("uploads/<uuid:track_id>/", apis.UploadDetailApi.as_view(), name="upload-detail"),
    # Flux SSE de la progression (hors ATOMIC_REQUESTS : ni transaction ni connexion tenue).
    path(
        "uploads/<uuid:track_id>/flux/",
        transaction.non_atomic_requests(AudioUploadFluxApi.as_view()),
        name="upload-flux",
    ),
    path("uploads/<uuid:track_id>/local/", apis.UploadLocalApi.as_view(), name="upload-local"),
    path("uploads/<uuid:track_id>/terminer/", apis.UploadFinishApi.as_view(), name="upload-finish"),
    path("lecture/etat/", apis.PlaybackStateApi.as_view(), name="playback-state"),
    path("recherche/", apis.SearchApi.as_view(), name="search"),
    path("bibliotheque/", apis.LibraryApi.as_view(), name="library"),
    path("evenements/", apis.EventsApi.as_view(), name="events"),
    path("accueil/", apis.HomeApi.as_view(), name="home"),
    path("pour-vous/", apis.ForYouApi.as_view(), name="for-you"),
    path("reglages/", apis.ListenerSettingsApi.as_view(), name="settings"),
    path("playlists/", apis.PlaylistListCreateApi.as_view(), name="playlists"),
    path("playlists/<uuid:playlist_id>/", apis.PlaylistDetailApi.as_view(), name="playlist-detail"),
    path("playlists/<uuid:playlist_id>/pistes/", apis.PlaylistTracksApi.as_view(), name="playlist-tracks"),
    path(
        "playlists/<uuid:playlist_id>/pistes/<uuid:track_id>/",
        apis.PlaylistTrackRemoveApi.as_view(),
        name="playlist-track-remove",
    ),
    path("playlists/<uuid:playlist_id>/ordre/", apis.PlaylistOrderApi.as_view(), name="playlist-order"),
    path("staff/sources/", apis.StaffSourcesApi.as_view(), name="staff-sources"),
    path("staff/pistes/", apis.StaffTracksApi.as_view(), name="staff-tracks"),
    path("staff/albums/", apis.StaffAlbumListCreateApi.as_view(), name="staff-albums"),
    path("staff/albums/<uuid:album_id>/", apis.StaffAlbumDetailApi.as_view(), name="staff-album-detail"),
    path("staff/albums/<uuid:album_id>/pochette/", apis.StaffAlbumCoverStartApi.as_view(), name="staff-album-cover"),
    path(
        "staff/albums/<uuid:album_id>/pochette/terminer/",
        apis.StaffAlbumCoverFinishApi.as_view(),
        name="staff-album-cover-finish",
    ),
    path(
        "staff/albums/<uuid:album_id>/pochette/<int:file_id>/local/",
        apis.StaffAlbumCoverLocalApi.as_view(),
        name="staff-album-cover-local",
    ),
    path("moderation/signalements/", apis.ReportListApi.as_view(), name="reports"),
    path("moderation/signalements/<int:report_id>/traiter/", apis.ReportHandleApi.as_view(), name="report-handle"),
]
