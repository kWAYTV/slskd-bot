"""Media pages yt-dlp understands: YouTube / YouTube Music, SoundCloud, Bandcamp.

Entries are free text (``Artist - Title``) without durations: a video's length
differs from the audio release and would break duration matching downstream.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from slskd_importer.soulseek.query import clean_query
from slskd_importer.sources.titles import (
    MAX_ENTRIES,
    has_separator,
    looks_like_track,
    strip_label_tag,
    strip_numbering,
    unique_entries,
)
from slskd_importer.sources.tracklist import SourceError, Tracklist

logger = logging.getLogger(__name__)

Extract = Callable[[str], dict[str, Any] | None]

UNREADABLE = "Could not read that link (private or removed?)."
NO_TRACKS = "No tracklist found on that page. Paste the track names as text instead."

_YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")
_MEDIA_HOSTS = (*_YOUTUBE_HOSTS, "soundcloud.com", "bandcamp.com")
# Share links from the SoundCloud app. yt-dlp has no extractor for them, so they are followed first.
_SHORT_LINK_HOSTS = ("on.soundcloud.com",)
_SHORT_LINK_TIMEOUT_SECS = 15
# YouTube's removed-item rows, and the stub title yt-dlp invents for an unavailable item ("youtube video #id").
_PLACEHOLDER_RE = re.compile(r"^(?:\[(?:private|deleted|unavailable) video\]|[\w-]+ video #\S+)$", re.IGNORECASE)
_MIX_MIN_CHAPTERS = 4
_MIX_MIN_SECONDS = 15 * 60
_TOPIC_RE = re.compile(r"\s+-\s+Topic$", re.IGNORECASE)
_ALBUM_PREFIX_RE = re.compile(r"^Album\s+-\s+", re.IGNORECASE)
_HANDLE_TAIL_RE = re.compile(r"\s+@\w+$")


def _on_host(url: str, hosts: tuple[str, ...]) -> bool:
    host = (urlsplit(url if "://" in url else f"https://{url}").hostname or "").lower()
    return any(host == known or host.endswith(f".{known}") for known in hosts)


def is_media_url(url: str) -> bool:
    """True for links on a host yt-dlp can read for us. No network."""
    return _on_host(url.strip(), _MEDIA_HOSTS)


class _QuietLog:
    """yt-dlp logger: per-item failures are expected (private videos, purchase-only tracks), so keep them at debug."""

    def debug(self, message: str) -> None:
        logger.debug("yt-dlp: %s", message)

    info = warning = debug

    def error(self, message: str) -> None:
        logger.warning("yt-dlp: %s", message)


def expand_short_link(url: str) -> str:
    """Follow a share link (``on.soundcloud.com/…``) to the page it points at; other URLs come back as they are."""
    if not _on_host(url, _SHORT_LINK_HOSTS):
        return url
    import httpx

    try:
        response = httpx.get(url, follow_redirects=True, timeout=_SHORT_LINK_TIMEOUT_SECS)
    except httpx.HTTPError:
        logger.warning("Could not follow the share link %s", url, exc_info=True)
        return url
    target = urlsplit(str(response.url))
    if response.status_code >= 400 or _on_host(str(response.url), _SHORT_LINK_HOSTS):
        logger.warning("Share link %s did not lead anywhere (HTTP %s)", url, response.status_code)
        return url
    # Drop the tracking query (?si=…&utm_…); a private link's secret is part of the path.
    return f"{target.scheme}://{target.netloc}{target.path}"


def _extract(url: str) -> dict[str, Any] | None:
    """Ask yt-dlp for metadata only.

    YouTube playlists are read flat (one request; entries carry title + channel).
    Flat SoundCloud / Bandcamp entries carry no usable title or artist,
    so those hosts are extracted in full.
    """
    import yt_dlp

    url = expand_short_link(url)
    options = {
        "extract_flat": "in_playlist" if _on_host(url, _YOUTUBE_HOSTS) else False,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": False,
        "playlistend": MAX_ENTRIES,
        "ignoreerrors": True,
        "ignore_no_formats_error": True,  # purchase-only Bandcamp tracks still have metadata
        "logger": _QuietLog(),
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(url, download=False)


def _artist(item: dict[str, Any]) -> tuple[str, bool]:
    """The item's artist and whether it came from a structured field (not the channel name)."""
    artists = item.get("artists")
    structured = (artists[0] if artists else None) or item.get("artist") or item.get("creator")
    if structured:
        return str(structured).strip(), True
    channel = item.get("channel") or item.get("uploader") or ""
    return _TOPIC_RE.sub("", str(channel)).strip(), False


def _query(item: dict[str, Any], fallback_artist: str = "") -> str:
    """Free-text ``Artist - Title`` for one video or track, or "" for a placeholder."""
    title = strip_label_tag(str(item.get("track") or item.get("title") or "").strip())
    if not title or _PLACEHOLDER_RE.match(title):
        return ""
    artist, structured = _artist(item)
    artist = artist or fallback_artist
    # A structured artist missing from the title means its dash is part of the track name ("Song - Live").
    named = not structured or artist.lower() in title.lower()
    if not artist or (has_separator(title) and named):
        return clean_query(title)
    return clean_query(f"{artist} - {title}")


def _chapter_queries(item: dict[str, Any]) -> list[str]:
    """Track-like chapter titles of a long DJ mix; empty when the item is not one."""
    chapters = item.get("chapters") or []
    if len(chapters) < _MIX_MIN_CHAPTERS or (item.get("duration") or 0) <= _MIX_MIN_SECONDS:
        return []
    titles = (strip_numbering(_HANDLE_TAIL_RE.sub("", str(chapter.get("title") or ""))) for chapter in chapters)
    return [clean_query(title) for title in titles if looks_like_track(title)]


def _is_album(info: dict[str, Any], title: str) -> bool:
    extractor = str(info.get("extractor_key") or "").lower()
    return (
        info.get("album_type") in {"album", "ep", "single", "compilation"}
        or "album" in extractor
        or str(info.get("id") or "").startswith("OLAK5uy_")
        or bool(_ALBUM_PREFIX_RE.match(title))
    )


def resolve_media(url: str, extract: Extract | None = None) -> Tracklist:
    """Turn a media link into wanted tracks. Blocking; *extract* maps a URL to a yt-dlp info dict."""
    try:
        info = (extract or _extract)(url)
    except Exception as exc:
        logger.info("yt-dlp could not read %s: %s", url, exc)
        raise SourceError(UNREADABLE) from exc
    if not info:
        raise SourceError(UNREADABLE)

    title = str(info.get("title") or "").strip()
    if info.get("_type") in {"playlist", "multi_video"} or "entries" in info:
        kind = "album" if _is_album(info, title) else "playlist"
        album_artist = str(info.get("album_artist") or "").strip()
        queries = [_query(item, album_artist) for item in info.get("entries") or [] if item]
        title = _ALBUM_PREFIX_RE.sub("", title)
    elif queries := _chapter_queries(info):
        kind = "mix"
    else:
        kind, queries = "track", [_query(info)]
        if not queries[0]:
            raise SourceError(UNREADABLE)

    entries = unique_entries(queries)
    if not entries:
        raise SourceError(NO_TRACKS)
    return Tracklist(name=title or entries[0].query, kind=kind, url=url, entries=entries)
