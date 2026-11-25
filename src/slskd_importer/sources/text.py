"""Typed or pasted track names: one wanted track per line.

Handles tracklists copied from anywhere: bullets, leading numbering and
timestamps (``01.``, ``[12:30]``), and trailing label brackets (``[Drumcode]``)
are stripped.
"""

from __future__ import annotations

import re

from slskd_importer.sources.titles import has_separator, is_unidentified, strip_numbering, strip_wrapping
from slskd_importer.sources.tracklist import Entry

_BULLET = re.compile(r"^\s*[-•*·▪]\s+")


def clean_line(line: str) -> str:
    """One tracklist line without bullet, numbering, timestamp, promo words or trailing ``[Label]``."""
    text = strip_numbering(_BULLET.sub("", line, count=1))
    text = strip_wrapping(text)
    return re.sub(r"\s{2,}", " ", text).strip()


def entries_from_lines(lines: list[str]) -> list[Entry]:
    """Entries for the lines that name a track; blanks, ``ID - ID`` rows and repeats are dropped."""
    entries: list[Entry] = []
    seen: set[str] = set()
    for line in lines:
        query = clean_line(line)
        if not query or query.lower() in seen:
            continue
        if has_separator(query) and is_unidentified(query):
            continue
        seen.add(query.lower())
        entries.append(Entry(query=query))
    return entries
