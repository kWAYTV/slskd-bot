"""Track identity and catalog lookup (Spotify)."""

from music_downloader.catalog.playlist import MAX_IMPORT_TRACKS, PlaylistInfo, PlaylistResolver
from music_downloader.catalog.spotify import SpotifyResolver
from music_downloader.catalog.track import TrackInfo

__all__ = [
    "MAX_IMPORT_TRACKS",
    "PlaylistInfo",
    "PlaylistResolver",
    "SpotifyResolver",
    "TrackInfo",
]
