"""Shared builders for download-queue tests."""

from __future__ import annotations

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.queue.store import QueueRepository
from slskd_importer.records.database import Database
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.sources.tracklist import Entry


def make_store(tmp_path) -> QueueRepository:
    return QueueRepository(Database(str(tmp_path / "queue.db")))


def make_track(title: str = "Bang Bang") -> TrackInfo:
    return TrackInfo(
        artist="Nancy Sinatra",
        title=title,
        album="How Does That Grab You?",
        duration_ms=162_000,
        spotify_url=f"https://open.spotify.com/track/{title}",
        year="1966",
    )


def make_result(idx: int = 0, extension: str = "flac") -> SearchResult:
    return SearchResult(
        username=f"user{idx}",
        filename=f"\\Music\\Nancy Sinatra - Bang Bang {idx}.{extension}",
        size=30_000_000,
        bit_depth=16,
        sample_rate=44100,
        length=162,
        has_free_slot=True,
    )


def make_batch(store: QueueRepository, entries: list[Entry] | None = None, **kwargs):
    entries = entries if entries is not None else [Entry(track=make_track())]
    kwargs.setdefault("message_id", 900)
    return store.create_batch(67890, 12345, "Test batch", "list", entries, **kwargs)
