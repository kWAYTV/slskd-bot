"""Official SoundCloud API client.

Client Credentials flow against ``secure.soundcloud.com/oauth/token``, then
the documented ``/resolve`` endpoint for exact artist/title.  Registration
requires an Artist Pro subscription.
https://developers.soundcloud.com/docs/api/

The official Python SDK is deprecated by SoundCloud; community packages work
by scraping a client_id from web bundles, which is fragile and undocumented —
so this client uses documented endpoints via plain HTTP.
"""

from __future__ import annotations

import logging
import time

import requests

from music_downloader.catalog.soundcloud import SoundCloudTrack, strip_artist_prefix

logger = logging.getLogger(__name__)

_TOKEN_ENDPOINT = "https://secure.soundcloud.com/oauth/token"
_RESOLVE_ENDPOINT = "https://api.soundcloud.com/resolve"
_TOKEN_EXPIRY_MARGIN_SECS = 60

REQUEST_TIMEOUT_SECS = 10


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
        return SoundCloudTrack(artist=artist, title=strip_artist_prefix(artist, title))

    @staticmethod
    def _resolve_request(url: str, token: str) -> requests.Response:
        return requests.get(
            _RESOLVE_ENDPOINT,
            params={"url": url},
            headers={"Authorization": f"OAuth {token}"},
            timeout=REQUEST_TIMEOUT_SECS,
        )

    def _token(self) -> str:
        """Cached access token; renew via refresh_token grant, else client_credentials."""
        if self._access_token and time.time() < self._expires_at - _TOKEN_EXPIRY_MARGIN_SECS:
            return self._access_token

        grant = (
            {"grant_type": "refresh_token", "refresh_token": self._refresh_token}
            if self._refresh_token
            else {"grant_type": "client_credentials"}
        )
        try:
            response = requests.post(
                _TOKEN_ENDPOINT,
                data=grant,
                auth=(self._client_id, self._client_secret),
                timeout=REQUEST_TIMEOUT_SECS,
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
