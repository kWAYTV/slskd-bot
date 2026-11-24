"""What every source produces: a named list of wanted tracks."""

from __future__ import annotations

from dataclasses import dataclass, field

from slskd_importer.catalog.track import TrackInfo


@dataclass(frozen=True)
class Entry:
    """One wanted track.

    *track* is set when the source knows the catalog identity (Spotify).
    Otherwise *query* holds free text, usually ``Artist - Title``, and the
    queue resolves it against the catalog when the item is processed.
    """

    query: str = ""
    track: TrackInfo | None = None

    @property
    def label(self) -> str:
        return self.track.filename if self.track else self.query


@dataclass
class Tracklist:
    """A resolved source. *kind* is ``track``, ``album``, ``playlist``, ``mix`` or ``list``."""

    name: str
    kind: str
    url: str = ""
    entries: list[Entry] = field(default_factory=list)


class SourceError(Exception):
    """A source could not be read. The message is shown to the user as is."""
