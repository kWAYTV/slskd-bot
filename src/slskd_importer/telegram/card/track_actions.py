"""Card buttons that act on one track: choose a copy, undo, send the file, fetch again.

Functions take the ``MusicBot`` instance as ``self``; ``card.callbacks`` dispatches to them.
"""

from __future__ import annotations

import asyncio
import logging

from slskd_importer.queue.batch import Batch, Item, ItemStatus
from slskd_importer.telegram.card import actions, board
from slskd_importer.telegram.card.status import ATTENTION

logger = logging.getLogger(__name__)


async def open_picker(self, query, batch: Batch, item: Item, page: int) -> None:
    """Show the copies found for a track, searching first when none are remembered."""
    self.cards.focus(batch.id, board.PICKER, item.id, page)
    finder = self.runner.pipeline.finder
    if finder.remembered(item.id) is not None:
        return
    await self.cards.draw(batch.id)  # "searching" while the search runs
    track = await self.runner.pipeline.identified(item)
    try:
        await finder.find(item.id, track)
    except Exception:
        logger.exception("Picker search failed for item %d", item.id)
        self.cards.focus(batch.id, board.ITEM, item.id)


async def get_copy(self, query, batch: Batch, item: Item, index: int) -> None:
    """Fetch the copy the requester chose. A track already saved is replaced by it once it arrives."""
    copies = self.runner.pipeline.finder.remembered(item.id)
    if copies is None or index >= len(copies.ranked) or item.status in (ItemStatus.pending, ItemStatus.working):
        return
    if batch.to_library and not self._can_save_library(query.from_user.id):
        return
    if item.status == ItemStatus.done and batch.to_library:
        # The saved file stays until the chosen copy has landed and passed its checks.
        self.runner.pipeline.replaces[item.id] = (item.saved_name, item.history_id)
    logger.info("chat=%s item %d: picked #%d %s", batch.chat_id, item.id, index + 1, copies.ranked[index].basename)
    self.cards.leave(batch.id)  # picked: back to where the track was opened from
    await self.runner.requeue(item, forced=True, pick=copies.ranked[index])


async def undo_save(self, query, batch: Batch, item: Item, _number: int) -> None:
    """Take a saved track back out of the library."""
    if item.status != ItemStatus.done or not batch.to_library or not self._can_save_library(query.from_user.id):
        return
    await asyncio.to_thread(self.shelf.remove, item.saved_name, item.history_id)
    await asyncio.to_thread(self.queue_store.update_item, item.id, status=ItemStatus.removed)
    logger.info("chat=%s item %d: removed %s from the library", batch.chat_id, item.id, item.saved_name)


async def send_file(self, query, batch: Batch, item: Item, _number: int) -> None:
    if item.status == ItemStatus.done and batch.to_library:
        await self._send_saved_file(batch, item)


async def fetch_again(self, query, batch: Batch, item: Item, _number: int) -> None:
    """Fetch a track that is owned, removed or cancelled, skipping the owned check."""
    if item.status in (ItemStatus.owned, ItemStatus.removed, ItemStatus.cancelled):
        self.cards.leave(batch.id)
        await self.runner.requeue(item, forced=True)


async def retry(self, query, batch: Batch, item: Item, _number: int) -> None:
    if item.status in (ItemStatus.failed, ItemStatus.no_match, ItemStatus.review):
        self.cards.leave(batch.id)
        await self.runner.requeue(item, forced=bool(item.forced))


async def skip(self, query, batch: Batch, item: Item, _number: int) -> None:
    """Leave a track that needs attention (lossy only, not found, failed); it can be fetched again later."""
    if item.status in (*ATTENTION, ItemStatus.no_match):
        self.cards.leave(batch.id)
        await asyncio.to_thread(self.queue_store.update_item, item.id, status=ItemStatus.cancelled)


TRACK_ACTIONS = {
    actions.PICKER: open_picker,
    actions.GET: get_copy,
    actions.UNDO: undo_save,
    actions.SEND: send_file,
    actions.AGAIN: fetch_again,
    actions.RETRY: retry,
    actions.SKIP: skip,
}
