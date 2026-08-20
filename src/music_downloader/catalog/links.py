"""Detect and parse pasted music links (Spotify tracks, SoundCloud tracks)."""

from __future__ import annotations

import re

# open.spotify.com/track/<id>, with optional /intl-xx/ locale segment,
# plus the spotify:track:<id> URI form.
_SPOTIFY_TRACK_URL_RE = re.compile(r"spotify\.com/(?:intl-[a-zA-Z-]+/)?track/([a-zA-Z0-9]+)")
_SPOTIFY_TRACK_URI_RE = re.compile(r"spotify:track:([a-zA-Z0-9]+)")

# soundcloud.com/<user>/<track-slug> — /sets/ paths are playlists, not tracks.
_SOUNDCLOUD_TRACK_RE = re.compile(r"https?://(?:www\.|m\.)?soundcloud\.com/([\w-]+)/(?!sets(?:/|\?|$))([\w-]+)[^\s]*")
# on.soundcloud.com short links redirect to the canonical track URL.
_SOUNDCLOUD_SHORT_RE = re.compile(r"https?://on\.soundcloud\.com/[\w]+")


def extract_spotify_track_id(text: str) -> str | None:
    """Return the Spotify track ID from a pasted link or URI, or None."""
    match = _SPOTIFY_TRACK_URL_RE.search(text) or _SPOTIFY_TRACK_URI_RE.search(text)
    return match.group(1) if match else None


def extract_soundcloud_url(text: str) -> str | None:
    """Return the first SoundCloud track URL (full or short link) in the text, or None."""
    match = _SOUNDCLOUD_TRACK_RE.search(text) or _SOUNDCLOUD_SHORT_RE.search(text)
    return match.group(0) if match else None
