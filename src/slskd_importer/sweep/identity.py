"""Resolve artist/title for a library file: tags first, then filename heuristics."""

from __future__ import annotations

import re

from slskd_importer.sweep.audit import Audit

# "01 - ", "01. ", "01 ", "1 - " at the start of a stem or title part.
_TRACK_PREFIX = re.compile(r"^\d{1,3}(?:\s*[-.]\s*|\s+)")

# Bracketed rip/format noise that is not part of the song title.
_JUNK_BRACKET = re.compile(
    r"\s*[\(\[](?:"
    r"digital\s*media|web|cd|vinyl|vinyl\s*rip|web\s*rip|"
    r"flac(?:\s*\d+\s*bit)?|wav|aiff|alac|mp3|aac|"
    r"\d{1,2}\s*bit|\d{2,3}(?:\.\d)?\s*khz?|\d{2,3}\s*kbps|"
    r"remaster(?:ed)?(?:\s*\d{4})?|explicit|clean|deluxe|bonus|"
    r"16.?44\.?1|24.?48|24.?96|24.?192"
    r")[\)\]]",
    re.IGNORECASE,
)


def strip_junk(text: str) -> str:
    """Drop rip/format brackets and tidy whitespace."""
    text = _JUNK_BRACKET.sub("", text or "")
    return re.sub(r"\s{2,}", " ", text).strip(" -._")


def parse_stem(stem: str) -> tuple[str, str]:
    """Best-effort ("Artist", "Title") from a library filename stem.

    Handles:
    - ``Artist - Title``
    - ``NN - Artist - Title`` / ``NN. Artist - Title``
    - ``Artist - Album - Title`` / ``Artist - Album - NN Title``
    - bracketed rip tags stripped from the title

    Returns ``("", stem)`` when no confident artist/title split exists.
    """
    raw = (stem or "").strip()
    if not raw:
        return "", ""

    rest = _TRACK_PREFIX.sub("", raw, count=1).strip() if _TRACK_PREFIX.match(raw) else raw
    parts = [p.strip() for p in rest.split(" - ") if p.strip()]

    if len(parts) >= 3:
        artist = parts[0]
        title = _TRACK_PREFIX.sub("", parts[-1], count=1).strip()
        artist, title = strip_junk(artist), strip_junk(title)
        return (artist, title) if artist and title else ("", raw)

    if len(parts) == 2:
        artist, title = strip_junk(parts[0]), strip_junk(parts[1])
        # "01 - Title" left a numeric "artist" after a bad strip — refuse.
        if artist.isdigit() or not artist or not title:
            return "", raw
        return artist, title

    return "", raw


def identity(original: Audit | None, stem: str) -> tuple[str, str]:
    """Artist/title for search and judging: tags win when both are present."""
    if original is not None:
        artist = strip_junk(original.artist or "")
        title = strip_junk(original.title or "")
        if artist and title:
            return artist, title
    return parse_stem(stem)
