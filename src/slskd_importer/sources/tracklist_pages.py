"""DJ tracklist sites: 1001Tracklists (schema.org microdata) and MixesDB (MediaWiki ordered lists)."""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from urllib.parse import urlsplit

from slskd_importer.sources.titles import looks_like_track, strip_numbering, unique_entries
from slskd_importer.sources.tracklist import SourceError, Tracklist

Fetch = Callable[[str], str]

BLOCKED_1001 = "1001Tracklists blocked the request. Copy the tracklist and paste it as text instead."
BLOCKED = "That site blocked the request. Copy the tracklist and paste it as text instead."
UNREADABLE = "Could not read that link (private or removed?)."
NO_TRACKS = "No tracklist found on that page. Paste the track names as text instead."

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
_BLOCKED_STATUS = frozenset({403, 429, 503})
# Cloudflare interstitial, and the Turnstile "you will be forwarded" page 1001Tracklists serves (HTTP 206).
_CHALLENGE_MARKERS = ("just a moment...", "turnstile-container", "you will be forwarded to the requested page")

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TITLE_SUFFIX_RE = re.compile(r"\s*\|\s*(?:DJ sets tracklists on )?(?:MixesDB|1001Tracklists).*$", re.IGNORECASE)
# 1001Tracklists: <div itemprop="tracks" itemtype="http://schema.org/MusicRecording"><meta itemprop="name" content="…">
_RECORDING_RE = re.compile(
    r'itemtype="https?://schema\.org/MusicRecording"[^>]*>\s*<meta\s+itemprop="name"\s+content="([^"]*)"',
    re.IGNORECASE,
)
# MixesDB: <h2 id="Tracklist"> followed by one or more <ol><li>[012] Artist - Title [Label]</li></ol>.
_MIXESDB_SECTION_RE = re.compile(r'id="Tracklist".*?(?=<h2|<!--|\Z)', re.IGNORECASE | re.DOTALL)
_LIST_ITEM_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_LABEL_TAIL_RE = re.compile(r"\s*\[[^\]]*\]\s*$")


def _host(url: str) -> str:
    return (urlsplit(url if "://" in url else f"https://{url}").hostname or "").lower()


def _is_1001(url: str) -> bool:
    return _host(url).endswith("1001tracklists.com") and "/tracklist/" in url


def _blocked_message(url: str) -> str:
    return BLOCKED_1001 if _is_1001(url) else BLOCKED


def _is_mixesdb(url: str) -> bool:
    # Mix pages are dated ("/w/2026-10-24_-_Artist_-_Show"); categories and special pages are not.
    return _host(url).endswith("mixesdb.com") and bool(re.search(r"/w/\d{4}", url))


def is_tracklist_page_url(url: str) -> bool:
    """True for a 1001Tracklists tracklist page or a MixesDB mix page. No network."""
    url = url.strip()
    return _is_1001(url) or _is_mixesdb(url)


def _fetch(url: str) -> str:
    import httpx

    try:
        response = httpx.get(url, headers={"User-Agent": _USER_AGENT}, follow_redirects=True, timeout=20)
    except httpx.HTTPError as exc:
        raise SourceError(UNREADABLE) from exc
    if response.status_code in _BLOCKED_STATUS:
        raise SourceError(_blocked_message(url))
    if response.status_code >= 400:
        raise SourceError(UNREADABLE)
    return response.text


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub("", fragment))).strip()


def _page_name(page: str) -> str:
    match = _TITLE_RE.search(page)
    return _TITLE_SUFFIX_RE.sub("", _text(match.group(1))) if match else ""


def _rows_1001(page: str) -> list[str]:
    return [html.unescape(name).strip() for name in _RECORDING_RE.findall(page)]


def _rows_mixesdb(page: str) -> list[str]:
    section = _MIXESDB_SECTION_RE.search(page)
    items = _LIST_ITEM_RE.findall(section.group(0)) if section else []
    return [_LABEL_TAIL_RE.sub("", strip_numbering(_text(item))) for item in items]


def resolve_tracklist_page(url: str, fetch: Fetch | None = None) -> Tracklist:
    """Read the identified tracks of a DJ set page. Blocking; *fetch* maps a URL to its HTML."""
    page = (fetch or _fetch)(url)
    rows = _rows_mixesdb(page) if _is_mixesdb(url) else _rows_1001(page)
    entries = unique_entries(row for row in rows if looks_like_track(row))
    if not entries:
        lowered = page.lower()
        if any(marker in lowered for marker in _CHALLENGE_MARKERS):
            raise SourceError(_blocked_message(url))
        raise SourceError(NO_TRACKS)
    return Tracklist(name=_page_name(page) or "Tracklist", kind="mix", url=url, entries=entries)
