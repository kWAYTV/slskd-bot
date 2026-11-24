"""DJ tracklist pages: 1001Tracklists (schema.org microdata)."""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from urllib.parse import urlsplit

from slskd_importer.sources.titles import looks_like_track, unique_entries
from slskd_importer.sources.tracklist import SourceError, Tracklist

Fetch = Callable[[str], str]

BLOCKED_1001 = "1001Tracklists blocked the request. Copy the tracklist and paste it as text instead."
UNREADABLE = "Could not read that link (private or removed?)."
NO_TRACKS = "No tracklist found on that page. Paste the track names as text instead."

_HOST_1001 = "1001tracklists.com"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
_BLOCKED_STATUS = frozenset({403, 429, 503})
# Cloudflare interstitial, and the Turnstile "you will be forwarded" page 1001Tracklists serves (HTTP 206).
_CHALLENGE_MARKERS = ("just a moment...", "turnstile-container", "you will be forwarded to the requested page")

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TITLE_SUFFIX_RE = re.compile(r"\s*\|\s*1001Tracklists.*$", re.IGNORECASE)
# <div itemprop="tracks" itemtype="http://schema.org/MusicRecording"><meta itemprop="name" content="…">
_RECORDING_RE = re.compile(
    r'itemtype="https?://schema\.org/MusicRecording"[^>]*>\s*<meta\s+itemprop="name"\s+content="([^"]*)"',
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")


def is_tracklist_page_url(url: str) -> bool:
    """True for a 1001Tracklists tracklist page. No network.

    The host must be the site itself or a subdomain of it, and the path a
    tracklist: the site's name appearing elsewhere in a URL does not count.
    """
    url = url.strip()
    parts = urlsplit(url if "://" in url else f"https://{url}")
    host = (parts.hostname or "").lower()
    on_site = host == _HOST_1001 or host.endswith(f".{_HOST_1001}")
    return on_site and parts.path.startswith("/tracklist/")


def _fetch(url: str) -> str:
    import httpx

    try:
        response = httpx.get(url, headers={"User-Agent": _USER_AGENT}, follow_redirects=True, timeout=20)
    except httpx.HTTPError as exc:
        raise SourceError(UNREADABLE) from exc
    if response.status_code in _BLOCKED_STATUS:
        raise SourceError(BLOCKED_1001)
    if response.status_code >= 400:
        raise SourceError(UNREADABLE)
    return response.text


def _page_name(page: str) -> str:
    match = _TITLE_RE.search(page)
    if not match:
        return ""
    title = re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub("", match.group(1)))).strip()
    return _TITLE_SUFFIX_RE.sub("", title)


def resolve_tracklist_page(url: str, fetch: Fetch | None = None) -> Tracklist:
    """Read the identified tracks of a DJ set page. Blocking; *fetch* maps a URL to its HTML."""
    page = (fetch or _fetch)(url)
    rows = [html.unescape(name).strip() for name in _RECORDING_RE.findall(page)]
    entries = unique_entries(row for row in rows if looks_like_track(row))
    if not entries:
        lowered = page.lower()
        if any(marker in lowered for marker in _CHALLENGE_MARKERS):
            raise SourceError(BLOCKED_1001)
        raise SourceError(NO_TRACKS)
    return Tracklist(name=_page_name(page) or "Tracklist", kind="mix", url=url, entries=entries)
