"""SoundCloud track lookup via the public oEmbed endpoint (no API key).

https://developers.soundcloud.com/docs/oembed — accepts any SoundCloud URL
and returns JSON with ``title`` (usually "Track Title by Artist") and
``author_name`` (the uploader).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

_OEMBED_ENDPOINT = "https://soundcloud.com/oembed"
_TIMEOUT_SECS = 10


@dataclass
class SoundCloudTrack:
    """Artist/title as advertised by SoundCloud (no duration — oEmbed has none)."""

    artist: str
    title: str

    @property
    def query(self) -> str:
        return f"{self.artist} - {self.title}" if self.artist else self.title


class SoundCloudResolver:
    """Resolves track names from SoundCloud links."""

    def resolve(self, url: str) -> SoundCloudTrack | None:
        """Resolve a SoundCloud track URL to artist/title, or None on failure."""
        try:
            canonical = self._follow_short_link(url)
            response = requests.get(
                _OEMBED_ENDPOINT,
                params={"format": "json", "url": canonical},
                timeout=_TIMEOUT_SECS,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:
            logger.warning("SoundCloud oEmbed lookup failed for %s", url, exc_info=True)
            return None
        except ValueError:
            logger.warning("SoundCloud oEmbed returned non-JSON for %s", url)
            return None

        track = _parse_oembed(payload)
        if track:
            logger.info("SoundCloud resolved: %s - %s", track.artist, track.title)
        else:
            logger.warning("SoundCloud oEmbed response had no usable title for %s", url)
        return track

    @staticmethod
    def _follow_short_link(url: str) -> str:
        """Expand on.soundcloud.com short links to the canonical track URL."""
        if "on.soundcloud.com" not in url:
            return url
        response = requests.head(url, allow_redirects=True, timeout=_TIMEOUT_SECS)
        return response.url


def _parse_oembed(payload: dict) -> SoundCloudTrack | None:
    """Split oEmbed 'Track Title by Artist' into artist/title."""
    title = (payload.get("title") or "").strip()
    author = (payload.get("author_name") or "").strip()
    if not title:
        return None

    suffix = f" by {author}"
    if author and title.endswith(suffix):
        return SoundCloudTrack(artist=author, title=title[: -len(suffix)].strip())
    return SoundCloudTrack(artist=author, title=title)
