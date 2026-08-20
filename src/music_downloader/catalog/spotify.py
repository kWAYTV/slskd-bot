"""Spotify catalog lookup. Client Credentials flow — no user login."""

import logging

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from music_downloader.catalog.track import TrackInfo

logger = logging.getLogger(__name__)


class SpotifyResolver:
    """Resolves track metadata from Spotify."""

    def __init__(self, client_id: str, client_secret: str):
        auth_manager = SpotifyClientCredentials(
            client_id=client_id,
            client_secret=client_secret,
        )
        self.sp = spotipy.Spotify(auth_manager=auth_manager)
        logger.info("Spotify client initialized")

    def search(self, query: str) -> TrackInfo | None:
        """
        Search Spotify for a track and return metadata.

        Args:
            query: Free-text search (e.g., "Nancy Sinatra Bang Bang")

        Returns:
            TrackInfo with resolved metadata, or None if not found.
        """
        try:
            results = self.sp.search(q=query, type="track", limit=1)
            tracks = results.get("tracks", {}).get("items", [])

            if not tracks:
                logger.warning(f"No Spotify results for: {query}")
                return None

            track = tracks[0]
            artist = track["artists"][0]["name"]
            title = track["name"]
            album = track["album"]["name"]
            duration_ms = track["duration_ms"]
            spotify_url = track["external_urls"].get("spotify", "")
            year = track["album"].get("release_date", "")[:4]

            info = TrackInfo(
                artist=artist,
                title=title,
                album=album,
                duration_ms=duration_ms,
                spotify_url=spotify_url,
                year=year,
            )
            logger.info(f"Spotify resolved: {info}")
            return info

        except Exception:
            logger.exception(f"Spotify search failed for: {query}")
            return None

    def get_track(self, track_id: str) -> TrackInfo | None:
        """Resolve a Spotify track ID (from a pasted link) to full metadata."""
        try:
            track = self.sp.track(track_id)
            if not track:
                return None
            info = TrackInfo(
                artist=track["artists"][0]["name"],
                title=track["name"],
                album=track["album"]["name"],
                duration_ms=track["duration_ms"],
                spotify_url=track["external_urls"].get("spotify", ""),
                year=track["album"].get("release_date", "")[:4],
            )
            logger.info(f"Spotify track link resolved: {info}")
            return info
        except Exception:
            logger.exception(f"Spotify track lookup failed for id: {track_id}")
            return None

    def search_multiple(self, query: str, limit: int = 5) -> list[TrackInfo]:
        """
        Search Spotify for multiple matching tracks.
        Useful when the query is ambiguous.

        Args:
            query: Free-text search.
            limit: Maximum number of results.

        Returns:
            List of TrackInfo objects.
        """
        try:
            results = self.sp.search(q=query, type="track", limit=limit)
            tracks = results.get("tracks", {}).get("items", [])

            return [
                TrackInfo(
                    artist=t["artists"][0]["name"],
                    title=t["name"],
                    album=t["album"]["name"],
                    duration_ms=t["duration_ms"],
                    spotify_url=t["external_urls"].get("spotify", ""),
                    year=t["album"].get("release_date", "")[:4],
                )
                for t in tracks
            ]

        except Exception:
            logger.exception(f"Spotify multi-search failed for: {query}")
            return []
