"""Spotify links: a track, an album or a playlist."""

from __future__ import annotations

from slskd_importer.catalog.links import extract_spotify_track_id
from slskd_importer.catalog.playlist import PlaylistResolver
from slskd_importer.catalog.spotify import SpotifyResolver
from slskd_importer.sources.tracklist import Entry, SourceError, Tracklist


def is_spotify_url(url: str) -> bool:
    return PlaylistResolver.is_spotify_url(url) or extract_spotify_track_id(url) is not None


def resolve_spotify(url: str, spotify: SpotifyResolver) -> Tracklist:
    """Resolve a Spotify track/album/playlist link. Blocking."""
    track_id = extract_spotify_track_id(url)
    if track_id:
        track = spotify.get_track(track_id)
        if track is None:
            raise SourceError("That Spotify link could not be resolved. Try the song title.")
        return Tracklist(name=track.filename, kind="track", url=url, entries=[Entry(track=track)])

    info = PlaylistResolver(spotify).resolve(url)
    if info is None or not info.tracks:
        raise SourceError("That Spotify playlist or album could not be read. Is it private?")
    return Tracklist(
        name=info.name,
        kind="album" if info.is_album else "playlist",
        url=url,
        entries=[Entry(track=track) for track in info.tracks],
    )
