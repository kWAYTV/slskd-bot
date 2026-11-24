"""Find a song anywhere in the collection by its file name.

The collection may be much larger than the folder the bot saves into
(Rekordbox folders, older years, other sources). A song counts as present when
a file named ``Artist - Title`` exists anywhere under the root, whatever the
case, accents, punctuation, track-number prefix or album in the middle
(``Artist - Album - Title``). Versions are kept apart: ``Title (Extended Mix)``
is not ``Title``.
"""

from __future__ import annotations

import os
import re
import time

from slskd_importer.catalog.names import normalize, same_artist
from slskd_importer.library.formats import AUDIO_SUFFIXES

REFRESH_SECS = 120
_TRACK_PREFIX = re.compile(r"^\d{1,3}(?:\s*[-.]\s*|\s+)(?=\S)")


def split_name(stem: str) -> tuple[str, str] | None:
    """``(artist, title)`` normalized from a file name without extension, or None when it names no artist."""
    parts = [part.strip() for part in stem.split(" - ") if part.strip()]
    if len(parts) >= 3 and parts[0].isdigit():
        parts = parts[1:]  # "01 - Artist - Title"
    if len(parts) < 2:
        return None
    artist = normalize(_TRACK_PREFIX.sub("", parts[0], count=1))
    title = normalize(_TRACK_PREFIX.sub("", parts[-1], count=1))
    return (artist, title) if artist and title else None


class LibraryIndex:
    """File names under *root*, re-read at most every ``REFRESH_SECS``. *exclude* folders are not part of it."""

    def __init__(self, root: str, exclude: tuple[str, ...] = ()) -> None:
        self.root = root
        self._exclude = tuple(os.path.realpath(path) for path in exclude if path)
        self._by_title: dict[str, list[tuple[str, str]]] = {}  # title -> [(artist, relative path)]
        self._read_at = 0.0

    def forget(self) -> None:
        """Make the next lookup read the folders again (after a save or an undo)."""
        self._read_at = 0.0

    def find(self, artist: str, title: str) -> str | None:
        """The relative path of a file holding this song, or None. Blocking."""
        wanted_artist, wanted_title = normalize(artist), normalize(title)
        if not wanted_artist or not wanted_title:
            return None
        if time.monotonic() - self._read_at > REFRESH_SECS or not self._read_at:
            self._read()
        for found_artist, path in self._by_title.get(wanted_title, ()):
            if same_artist(wanted_artist, found_artist) and os.path.isfile(os.path.join(self.root, path)):
                return path
        return None

    def _read(self) -> None:
        by_title: dict[str, list[tuple[str, str]]] = {}
        for folder, subfolders, files in os.walk(self.root):
            subfolders[:] = [
                name
                for name in subfolders
                if not name.startswith(".") and os.path.realpath(os.path.join(folder, name)) not in self._exclude
            ]
            for name in files:
                stem, suffix = os.path.splitext(name)
                if name.startswith(".") or suffix.lower() not in AUDIO_SUFFIXES:
                    continue
                parsed = split_name(stem)
                if parsed is None:
                    continue
                relative = os.path.relpath(os.path.join(folder, name), self.root).replace(os.sep, "/")
                by_title.setdefault(parsed[1], []).append((parsed[0], relative))
        self._by_title = by_title
        self._read_at = time.monotonic()
