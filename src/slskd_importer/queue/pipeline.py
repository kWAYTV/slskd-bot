"""One queue item, start to finish: identify, search, fetch, check, then save or deliver.

No one is asked along the way. Items that need a human (only lossy copies,
nothing found, every copy failed) end in a status the requester can act on.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from slskd_importer.catalog.lookup import identify
from slskd_importer.catalog.spotify import SpotifyResolver
from slskd_importer.catalog.track import TrackInfo
from slskd_importer.library.files import FileProcessor
from slskd_importer.library.lossless import CHECKABLE_EXTENSIONS, analyze_lossless
from slskd_importer.queue import progress as phases
from slskd_importer.queue.batch import Batch, Item, ItemStatus
from slskd_importer.queue.copies import CopyFinder
from slskd_importer.queue.fetch import Landed, discard, fetch
from slskd_importer.queue.progress import Progress
from slskd_importer.queue.shelf import LibraryShelf
from slskd_importer.queue.store import QueueRepository
from slskd_importer.settings.config import Config
from slskd_importer.soulseek.client import SlskdClient
from slskd_importer.soulseek.result import DownloadStatus, SearchResult

logger = logging.getLogger(__name__)

# Copies fetched per item before giving up.
MAX_TRIES = 3
# An automatically chosen copy that sits this long in its peer's upload queue is dropped for the next
# one, so a busy peer cannot hold a queue slot for the whole download timeout.
QUEUE_PATIENCE_SECS = 90
# A lossless verdict is stored on the item as ``verdict:<KIND>:<cutoff kHz>`` so a front end can word it.
VERDICT_PREFIX = "verdict:"

Report = Callable[[Progress], None]
# Hands a fetched file to the requester (batch, item, track, copy, path, quality); True when it reached them.
DeliverHook = Callable[[Batch, Item, TrackInfo, SearchResult, str, str], Awaitable[bool]]


def describe_copy(result: SearchResult) -> str:
    """``FLAC · 16/44.1 · 31 MB`` for a card line."""
    parts = [result.extension.upper() or "?", result.quality_short, f"{result.size_mb:.0f} MB"]
    return " · ".join(part for part in parts if part)


class ItemPipeline:
    def __init__(
        self,
        *,
        config: Config,
        spotify: SpotifyResolver,
        slskd: SlskdClient,
        processor: FileProcessor,
        store: QueueRepository,
        finder: CopyFinder,
        shelf: LibraryShelf,
    ) -> None:
        self._config = config
        self._spotify = spotify
        self._slskd = slskd
        self._processor = processor
        self._store = store
        self.finder = finder
        self.shelf = shelf
        self.deliver: DeliverHook | None = None
        # A copy the requester picked by hand for an item: fetched as is, never second-guessed.
        self.picks: dict[int, SearchResult] = {}
        # The saved file (name, history id) a picked copy replaces; removed once the new copy is ready to place.
        self.replaces: dict[int, tuple[str, int | None]] = {}
        # (peer, remote path) -> (lock, items waiting on or holding it)
        self._copy_locks: dict[tuple[str, str], tuple[asyncio.Lock, int]] = {}

    async def identified(self, item: Item) -> TrackInfo:
        """The item's catalog identity, looked up and stored on first use."""
        track = item.track
        if track is None:
            track = await asyncio.to_thread(identify, self._spotify, item.query)
            await asyncio.to_thread(self._store.set_identity, item.id, track)
        return track

    async def run(self, batch: Batch, item: Item, report: Report) -> None:
        if item.track is None:
            report(Progress(phases.IDENTIFYING))
        track = await self.identified(item)
        pick = self.picks.pop(item.id, None)
        replaces = self.replaces.pop(item.id, None)

        if pick is None and batch.to_library and not item.forced:
            owned = await asyncio.to_thread(self.shelf.owned_as, track)
            if owned:
                await self._finish(item, ItemStatus.owned, saved_name=owned)
                return

        if pick is not None:
            copies = [pick]
        else:
            report(Progress(phases.SEARCHING))
            found = await self.finder.find(item.id, track)
            if not found.ranked:
                await self._finish(item, ItemStatus.no_match)
                return
            if batch.asks_which_copy or not self._config.auto_pick:
                await self._finish(item, ItemStatus.choose)
                return
            if found.lossy:
                best = found.ranked[0]
                await self._finish(item, ItemStatus.review, detail=describe_copy(best))
                return
            copies = found.ranked[:MAX_TRIES]

        notes: list[str] = []
        for result in copies:
            note = await self._try_copy(batch, item, track, result, report, trusted=pick is not None, replaces=replaces)
            if note is None:
                return
            logger.info("Queue item %d: %s from %s: %s", item.id, result.basename, result.username, note)
            notes.append(note)
        await self._finish(item, ItemStatus.failed, detail="; ".join(notes)[:300])

    async def _try_copy(
        self,
        batch: Batch,
        item: Item,
        track: TrackInfo,
        result: SearchResult,
        report: Report,
        *,
        trusted: bool,
        replaces: tuple[str, int | None] | None = None,
    ) -> str | None:
        """Fetch one copy and finish the item with it. Returns why it was not used, or None on success."""

        async def on_progress(status: DownloadStatus) -> None:
            report(Progress(phases.DOWNLOADING, status.percent_complete, status.is_queued))

        # Two items wanting the same remote file (two people asking for one song) share one
        # slskd transfer and one file on disk: take turns, or one discards what the other is copying.
        key = (result.username, result.filename)
        lock, users = self._copy_locks.get(key, (asyncio.Lock(), 0))
        self._copy_locks[key] = (lock, users + 1)
        try:
            async with lock:
                report(Progress(phases.DOWNLOADING, 0.0))
                landed = await fetch(
                    self._slskd,
                    self._processor,
                    result,
                    self._config.download_timeout_secs,
                    on_progress,
                    # A copy picked by hand is worth waiting for; an automatic one has alternatives.
                    queue_patience_secs=None if trusted else QUEUE_PATIENCE_SECS,
                )
                if not landed.ok:
                    return landed.error
                try:
                    return await self._use_copy(
                        batch, item, track, result, landed, report, trusted=trusted, replaces=replaces
                    )
                except BaseException:
                    await discard(self._slskd, self._processor, result, landed.path, landed.transfer_id)
                    raise
        finally:
            lock, users = self._copy_locks[key]
            if users > 1:
                self._copy_locks[key] = (lock, users - 1)
            else:
                del self._copy_locks[key]

    async def _use_copy(
        self,
        batch: Batch,
        item: Item,
        track: TrackInfo,
        result: SearchResult,
        landed: Landed,
        report: Report,
        *,
        trusted: bool,
        replaces: tuple[str, int | None] | None = None,
    ) -> str | None:
        verdict = None
        if result.extension in CHECKABLE_EXTENSIONS:
            report(Progress(phases.CHECKING))
            verdict = await asyncio.to_thread(analyze_lossless, landed.path)
        if verdict is not None and verdict.verdict == "FAKE" and not trusted:
            await discard(self._slskd, self._processor, result, landed.path, landed.transfer_id)
            return f"fake lossless (cutoff {verdict.cutoff_khz:.1f} kHz)"

        quality = describe_copy(result)
        detail = f"{VERDICT_PREFIX}{verdict.verdict}:{verdict.cutoff_khz:.1f}" if verdict else ""
        if batch.to_library:
            report(Progress(phases.SAVING))
            if replaces is not None:
                # Only now, with the new copy fetched and checked, does the old one go.
                await asyncio.to_thread(self.shelf.remove, *replaces)
            placed = await self.shelf.place(track, result, landed.path, batch.chat_id)
            await discard(self._slskd, self._processor, result, landed.path, landed.transfer_id)
            if placed is None:
                return "could not be saved to the library"
            # A copy the audio check does not vouch for is saved, then put back in front of the requester.
            sound = verdict is None or verdict.verdict == "AUTHENTIC"
            await self._finish(
                item,
                ItemStatus.done if sound else ItemStatus.doubt,
                detail=detail,
                saved_name=placed.name,
                quality=quality,
                history_id=placed.history_id,
            )
            return None

        report(Progress(phases.SENDING))
        delivered = self.deliver is not None and await self.deliver(batch, item, track, result, landed.path, quality)
        await discard(self._slskd, self._processor, result, landed.path, landed.transfer_id)
        outcome = "delivered" if delivered else "failed"
        await asyncio.to_thread(self.shelf.record, track, result, outcome, batch.chat_id)
        if not delivered:
            return "could not be sent to the chat"
        await self._finish(item, ItemStatus.done, detail=detail, quality=quality)
        return None

    async def _finish(self, item: Item, status: ItemStatus, **fields: object) -> None:
        await asyncio.to_thread(self._store.update_item, item.id, status=status, **fields)
