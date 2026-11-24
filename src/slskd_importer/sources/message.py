"""Turn one chat message into a tracklist: links are resolved, other lines are track names."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from slskd_importer.catalog.spotify import SpotifyResolver
from slskd_importer.sources.media import is_media_url, resolve_media
from slskd_importer.sources.spotify import is_spotify_url, resolve_spotify
from slskd_importer.sources.text import entries_from_lines
from slskd_importer.sources.tracklist import Entry, SourceError, Tracklist
from slskd_importer.sources.tracklist_pages import is_tracklist_page_url, resolve_tracklist_page

logger = logging.getLogger(__name__)

MAX_ENTRIES = 500
_LINK = re.compile(r"(https?://\S+|spotify:(?:track|album|playlist):\w+)")


def resolve_link(url: str, spotify: SpotifyResolver) -> Tracklist:
    """Resolve one link with the source that understands it. Blocking."""
    if is_spotify_url(url):
        return resolve_spotify(url, spotify)
    if is_tracklist_page_url(url):
        return resolve_tracklist_page(url)
    if is_media_url(url):
        return resolve_media(url)
    host = urlparse(url).netloc or url
    raise SourceError(f"I can't read links from {host} yet. Paste the track names as text instead.")


def read_message(text: str, spotify: SpotifyResolver) -> Tracklist:
    """The tracklist a message asks for. Blocking.

    Each line is a link or a track name. One link gives that source's own
    tracklist; anything else is merged into one list. Raises SourceError when
    nothing usable is found.
    """
    entries: list[Entry] = []
    sources: list[Tracklist] = []
    errors: list[SourceError] = []
    plain: list[str] = []

    for line in text.splitlines():
        link = _LINK.search(line)
        if not link:
            plain.append(line)
            continue
        try:
            sources.append(resolve_link(link.group(1).rstrip(".,;)"), spotify))
        except SourceError as exc:
            logger.info("Source failed for %s: %s", link.group(1), exc)
            errors.append(exc)

    typed = entries_from_lines(plain)
    for source in sources:
        entries.extend(source.entries)
    entries.extend(typed)
    entries = entries[:MAX_ENTRIES]

    if not entries:
        raise errors[0] if errors else SourceError("Send a song name or a link.")
    if len(sources) == 1 and not typed:
        return Tracklist(sources[0].name, sources[0].kind, sources[0].url, entries)
    if len(entries) == 1:
        return Tracklist(entries[0].label, "track", "", entries)
    return Tracklist(f"{len(entries)} tracks", "list", "", entries)
