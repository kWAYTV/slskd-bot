"""SoundCloud link resolution: official API first, public oEmbed fallback.

The oEmbed endpoint needs no key and returns ``title`` (usually
"Track Title by Artist") plus ``author_name``.
https://developers.soundcloud.com/docs/oembed
"""

from __future__ import annotations

import logging

import requests

from music_downloader.catalog.soundcloud import SoundCloudTrack, strip_artist_prefix
from music_downloader.catalog.soundcloud_api import REQUEST_TIMEOUT_SECS, SoundCloudApi

logger = logging.getLogger(__name__)

_OEMBED_ENDPOINT = "https://soundcloud.com/oembed"


class SoundCloudResolver:
    """Resolves track names from SoundCloud links (official API first, oEmbed fallback)."""

    def __init__(self, client_id: str = "", client_secret: str = ""):
        self._api = SoundCloudApi(client_id, client_secret) if client_id and client_secret else None
        if self._api:
            logger.info("SoundCloud official API credentials configured")

    def resolve(self, url: str) -> SoundCloudTrack | None:
        """Resolve a SoundCloud track URL to artist/title, or None on failure."""
        try:
            canonical = self._follow_short_link(url)
        except requests.RequestException:
            logger.warning("SoundCloud short link expansion failed for %s", url, exc_info=True)
            return None

        if self._api:
            track = self._api.resolve_track(canonical)
            if track:
                logger.info("SoundCloud resolved via official API: %s - %s", track.artist, track.title)
                return track
            logger.info("SoundCloud official API could not resolve %s, falling back to oEmbed", url)

        return self._resolve_oembed(canonical, url)

    @staticmethod
    def _resolve_oembed(canonical: str, original_url: str) -> SoundCloudTrack | None:
        try:
            response = requests.get(
                _OEMBED_ENDPOINT,
                params={"format": "json", "url": canonical},
                timeout=REQUEST_TIMEOUT_SECS,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:
            logger.warning("SoundCloud oEmbed lookup failed for %s", original_url, exc_info=True)
            return None
        except ValueError:
            logger.warning("SoundCloud oEmbed returned non-JSON for %s", original_url)
            return None

        track = parse_oembed(payload)
        if not track:
            logger.warning("SoundCloud oEmbed response had no usable title for %s", original_url)
            return None
        logger.info("SoundCloud resolved via oEmbed: %s - %s", track.artist, track.title)
        return track

    @staticmethod
    def _follow_short_link(url: str) -> str:
        """Expand on.soundcloud.com short links to the canonical track URL."""
        if "on.soundcloud.com" not in url:
            return url
        response = requests.head(url, allow_redirects=True, timeout=REQUEST_TIMEOUT_SECS)
        return response.url


def parse_oembed(payload: dict) -> SoundCloudTrack | None:
    """Split oEmbed 'Track Title by Artist' into artist/title."""
    title = (payload.get("title") or "").strip()
    author = (payload.get("author_name") or "").strip()
    if not title:
        return None

    suffix = f" by {author}"
    if author and title.endswith(suffix):
        title = title[: -len(suffix)].strip()
    return SoundCloudTrack(artist=author, title=strip_artist_prefix(author, title))
