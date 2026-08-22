"""Detect and parse pasted music links (Spotify tracks)."""

from __future__ import annotations

import re

# open.spotify.com/track/<id>, with optional /intl-xx/ locale segment,
# plus the spotify:track:<id> URI form.
_SPOTIFY_TRACK_URL_RE = re.compile(r"spotify\.com/(?:intl-[a-zA-Z-]+/)?track/([a-zA-Z0-9]+)")
_SPOTIFY_TRACK_URI_RE = re.compile(r"spotify:track:([a-zA-Z0-9]+)")


def extract_spotify_track_id(text: str) -> str | None:
    """Return the Spotify track ID from a pasted link or URI, or None."""
    match = _SPOTIFY_TRACK_URL_RE.search(text) or _SPOTIFY_TRACK_URI_RE.search(text)
    return match.group(1) if match else None
