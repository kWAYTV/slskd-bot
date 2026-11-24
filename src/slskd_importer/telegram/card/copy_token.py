"""The number a copy button carries: its place in the list, plus a check that it is still that copy.

A track's copies can be searched again while an old picker is still on screen;
without the check a tap on ``#2`` would fetch whatever is second in the new list.
"""

from __future__ import annotations

import zlib

from slskd_importer.soulseek.result import SearchResult

_PLACES = 100  # more than the copies remembered per track


def copy_number(index: int, copy: SearchResult) -> int:
    check = zlib.crc32(f"{copy.username}|{copy.filename}".encode()) % 9000 + 1
    return index + _PLACES * check


def copy_at(ranked: list[SearchResult], number: int) -> SearchResult | None:
    """The copy a button number points at, or None when the list changed since the button was drawn."""
    index = number % _PLACES
    if index >= len(ranked) or copy_number(index, ranked[index]) != number:
        return None
    return ranked[index]
