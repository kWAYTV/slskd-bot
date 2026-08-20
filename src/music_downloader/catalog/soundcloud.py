"""SoundCloud track lookup.

Two resolution paths, most-official first:

1. **Official API** (when ``SOUNDCLOUD_CLIENT_ID``/``SOUNDCLOUD_CLIENT_SECRET``
   are configured — registration requires an Artist Pro subscription):
   Client Credentials flow against ``secure.soundcloud.com/oauth/token``, then
   the documented ``/resolve`` endpoint for exact artist/title.
   https://developers.soundcloud.com/docs/api/

2. **Public oEmbed endpoint** (zero-config fallback, no key required):
   returns ``title`` (usually "Track Title by Artist") and ``author_name``.
   https://developers.soundcloud.com/docs/oembed

The official Python SDK is deprecated by SoundCloud; community packages work
by scraping a client_id from web bundles, which is fragile and undocumented —
so both paths here use documented endpoints via plain HTTP.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

_OEMBED_ENDPOINT = "https://soundcloud.com/oembed"
_TOKEN_ENDPOINT = "https://secure.soundcloud.com/oauth/token"
_RESOLVE_ENDPOINT = "https://api.soundcloud.com/resolve"
_TIMEOUT_SECS = 10
_TOKEN_EXPIRY_MARGIN_SECS = 60


@dataclass
class SoundCloudTrack:
    """Artist/title as advertised by SoundCloud."""

    artist: str
    title: str

    @property
    def query(self) -> str:
        return f"{self.artist} - {self.title}" if self.artist else self.title


class SoundCloudApi:
    """Official SoundCloud API client (Client Credentials flow, token cached + refreshed)."""

    def __init__(self, client_id: str, client_secret: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token = ""
        self._refresh_token = ""
        self._expires_at = 0.0

    def resolve_track(self, url: str) -> SoundCloudTrack | None:
        """Resolve a track URL via the documented /resolve endpoint."""
        token = self._token()
        if not token:
            return None
        try:
            response = self._resolve_request(url, token)
            if response.status_code == 401:
                # Token revoked server-side — force one re-auth and retry.
                self._access_token = ""
                token = self._token()
                if not token:
                    return None
                response = self._resolve_request(url, token)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            logger.warning("SoundCloud API resolve failed for %s", url, exc_info=True)
            return None

        if data.get("kind") != "track":
            logger.info("SoundCloud URL is not a track (kind=%s): %s", data.get("kind"), url)
            return None
        title = (data.get("title") or "").strip()
        if not title:
            return None
        publisher = data.get("publisher_metadata") or {}
        artist = (publisher.get("artist") or "").strip() or (data.get("user") or {}).get("username", "").strip()
        return SoundCloudTrack(artist=artist, title=title)

    @staticmethod
    def _resolve_request(url: str, token: str) -> requests.Response:
        return requests.get(
            _RESOLVE_ENDPOINT,
            params={"url": url},
            headers={"Authorization": f"OAuth {token}"},
            timeout=_TIMEOUT_SECS,
        )

    def _token(self) -> str:
        """Cached access token; renew via refresh_token grant, else client_credentials."""
        if self._access_token and time.time() < self._expires_at - _TOKEN_EXPIRY_MARGIN_SECS:
            return self._access_token

        if self._refresh_token:
            grant = {"grant_type": "refresh_token", "refresh_token": self._refresh_token}
        else:
            grant = {"grant_type": "client_credentials"}
        try:
            response = requests.post(
                _TOKEN_ENDPOINT,
                data=grant,
                auth=(self._client_id, self._client_secret),
                timeout=_TIMEOUT_SECS,
            )
            if not response.ok and self._refresh_token:
                # Refresh tokens are single-use; fall back to a fresh grant.
                self._refresh_token = ""
                return self._token()
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            logger.warning("SoundCloud token request failed", exc_info=True)
            return ""

        self._access_token = payload.get("access_token", "")
        self._refresh_token = payload.get("refresh_token", "")
        self._expires_at = time.time() + payload.get("expires_in", 3600)
        return self._access_token


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
                timeout=_TIMEOUT_SECS,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:
            logger.warning("SoundCloud oEmbed lookup failed for %s", original_url, exc_info=True)
            return None
        except ValueError:
            logger.warning("SoundCloud oEmbed returned non-JSON for %s", original_url)
            return None

        track = _parse_oembed(payload)
        if track:
            logger.info("SoundCloud resolved via oEmbed: %s - %s", track.artist, track.title)
        else:
            logger.warning("SoundCloud oEmbed response had no usable title for %s", original_url)
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
