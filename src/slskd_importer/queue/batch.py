"""The download queue's records: a batch per chat message, an item per wanted track."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from slskd_importer.catalog.track import TrackInfo


class Destination(StrEnum):
    library = "library"  # placed in OUTPUT_DIR
    deliver = "deliver"  # sent to the requester's chat, never placed in the library


class BatchStatus(StrEnum):
    active = "active"
    done = "done"
    cancelled = "cancelled"


class ItemStatus(StrEnum):
    pending = "pending"
    working = "working"
    done = "done"  # saved to the library, or delivered
    doubt = "doubt"  # saved, but the audio check says it may be a transcode: keep it or pick another
    owned = "owned"  # already in the library, not fetched
    review = "review"  # only lossy copies exist: the requester picks one or leaves it
    choose = "choose"  # a song asked for on its own: the requester picks the copy
    no_match = "no_match"
    failed = "failed"
    removed = "removed"  # saved, then undone
    cancelled = "cancelled"


OPEN_STATUSES = (ItemStatus.pending, ItemStatus.working)
RETRYABLE_STATUSES = (ItemStatus.failed, ItemStatus.no_match)
# Waiting for the requester to pick a copy or let the track go; nothing is saved yet.
WAITING_STATUSES = (ItemStatus.choose, ItemStatus.review)
# The track's file is in the library.
SAVED_STATUSES = (ItemStatus.done, ItemStatus.doubt)


@dataclass
class Batch:
    id: int
    chat_id: int
    user_id: int
    name: str
    kind: str
    source_url: str
    destination: str
    status: str
    message_id: int | None
    query_message_id: int | None
    created_at: str
    updated_at: str

    @property
    def to_library(self) -> bool:
        return self.destination == Destination.library

    @property
    def asks_which_copy(self) -> bool:
        """A single requested song is never fetched blind, whatever AUTO_PICK says.

        Lists, playlists and tracklists also wait for a pick per track unless AUTO_PICK is on.
        """
        return self.kind == "track"


@dataclass
class Item:
    id: int
    batch_id: int
    position: int
    query: str
    artist: str
    title: str
    album: str
    duration_ms: int
    spotify_url: str
    year: str
    status: str
    detail: str
    saved_name: str
    quality: str
    history_id: int | None
    forced: int
    created_at: str
    updated_at: str
    # The copy picked by hand (JSON, see queue.pick), or "" when the queue chooses.
    pick: str = ""

    @property
    def identified(self) -> bool:
        return bool(self.title)

    @property
    def track(self) -> TrackInfo | None:
        """The catalog identity, once the item has one."""
        if not self.identified:
            return None
        return TrackInfo(
            artist=self.artist,
            title=self.title,
            album=self.album,
            duration_ms=self.duration_ms,
            spotify_url=self.spotify_url,
            year=self.year,
        )

    @property
    def confirmed(self) -> bool:
        """The identity came from a catalog (it has a length, an album or a link), not just from the text."""
        return bool(self.duration_ms or self.spotify_url or self.album)

    @property
    def label(self) -> str:
        """``Artist — Title``, or the raw query before the item is identified."""
        if not self.identified:
            return self.query
        return f"{self.artist} — {self.title}" if self.artist else self.title
