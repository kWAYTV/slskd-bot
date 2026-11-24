"""Card buttons that act on one track: choose a copy, keep, undo, send the file, fetch again, skip.

Functions take the ``MusicBot`` instance as ``self``; ``card.callbacks`` dispatches to them.
"""

from __future__ import annotations

import asyncio
import logging

from slskd_importer.queue.batch import OPEN_STATUSES, RETRYABLE_STATUSES, SAVED_STATUSES, Batch, Item, ItemStatus
from slskd_importer.telegram.card import actions, board
from slskd_importer.telegram.card.copy_token import copy_at
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


async def done_with(self, batch: Batch, item: Item) -> None:
    """The requester has dealt with *item*: show the next waiting track when going through them, else go back."""
    if self.cards.view_of(batch.id).tour:
        following = await asyncio.to_thread(self.queue_store.next_waiting, batch.id, item.position)
        if following is not None:
            await open_picker(self, None, batch, following, 0)
            return
    self.cards.leave(batch.id)


async def get_copy(self, query, batch: Batch, item: Item, number: int) -> None:
    """Fetch the copy the requester chose.

    A track already saved keeps its file until the chosen copy has landed and passed its checks;
    the pipeline then replaces it.
    """
    copies = self.runner.pipeline.finder.remembered(item.id)
    copy = copy_at(copies.ranked, number) if copies is not None else None
    if copy is None or item.status in OPEN_STATUSES or self.cards.just_opened(batch.id):
        return
    if batch.to_library and not self._can_save_library(query.from_user.id):
        return
    logger.info("chat=%s item %d: picked %s from %s", batch.chat_id, item.id, copy.basename, copy.username)
    await self.runner.requeue(item, forced=True, pick=copy)
    await done_with(self, batch, item)


async def keep(self, query, batch: Batch, item: Item, _number: int) -> None:
    """Keep a saved copy although the audio check doubts it."""
    if item.status == ItemStatus.doubt:
        await asyncio.to_thread(self.queue_store.update_item, item.id, status=ItemStatus.done)
        self.cards.leave(batch.id)


async def undo_save(self, query, batch: Batch, item: Item, _number: int) -> None:
    """Take a saved track back out of the library."""
    if item.status not in SAVED_STATUSES or not batch.to_library or not self._can_save_library(query.from_user.id):
        return
    await asyncio.to_thread(self.shelf.remove, item.saved_name, item.history_id)
    await asyncio.to_thread(self.queue_store.update_item, item.id, status=ItemStatus.removed)
    logger.info("chat=%s item %d: removed %s from the library", batch.chat_id, item.id, item.saved_name)
    self.cards.leave(batch.id)


async def send_file(self, query, batch: Batch, item: Item, _number: int) -> None:
    if item.status in SAVED_STATUSES and batch.to_library:
        await self._send_saved_file(batch, item)


async def fetch_again(self, query, batch: Batch, item: Item, _number: int) -> None:
    """Fetch a track that is owned, removed or cancelled, skipping the owned check."""
    if item.status in (ItemStatus.owned, ItemStatus.removed, ItemStatus.cancelled):
        await self.runner.requeue(item, forced=True)
        self.cards.leave(batch.id)


async def retry(self, query, batch: Batch, item: Item, _number: int) -> None:
    """Run a track again: the same copy when one was picked, a new search otherwise."""
    if item.status in (*RETRYABLE_STATUSES, ItemStatus.review):
        await self.runner.requeue(item, forced=bool(item.forced), same_copy=True)
        self.cards.leave(batch.id)


async def skip(self, query, batch: Batch, item: Item, _number: int) -> None:
    """Let a track go (waiting for a pick, lossy only, not found, failed); it can be fetched again later."""
    if item.status in (*ATTENTION, *RETRYABLE_STATUSES) and item.status != ItemStatus.doubt:
        await asyncio.to_thread(self.queue_store.update_item, item.id, status=ItemStatus.cancelled)
        await done_with(self, batch, item)


TRACK_ACTIONS = {
    actions.PICKER: open_picker,
    actions.GET: get_copy,
    actions.KEEP: keep,
    actions.UNDO: undo_save,
    actions.SEND: send_file,
    actions.AGAIN: fetch_again,
    actions.RETRY: retry,
    actions.SKIP: skip,
}
