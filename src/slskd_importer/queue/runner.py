"""Runs the download queue: a fixed number of items at a time, fairly across batches."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

from slskd_importer.queue.batch import Item, ItemStatus
from slskd_importer.queue.pick import encode_pick
from slskd_importer.queue.pipeline import ItemPipeline
from slskd_importer.queue.progress import Progress
from slskd_importer.queue.store import QueueRepository
from slskd_importer.soulseek.errors import SlskdUnavailableError
from slskd_importer.soulseek.result import SearchResult

logger = logging.getLogger(__name__)

# Transfers allowed to wait in peer queues at once, beyond the working slots.
MAX_PARKED = 20

# Called with a batch id whenever something about that batch changed. Must not block.
ChangeHook = Callable[[int], None]


class QueueRunner:
    def __init__(self, store: QueueRepository, pipeline: ItemPipeline, workers: int) -> None:
        self.store = store
        self.pipeline = pipeline
        self.workers = max(1, workers)
        self.progress: dict[int, Progress] = {}
        self.on_change: ChangeHook | None = None
        self._tasks: dict[int, tuple[int, asyncio.Task]] = {}  # item id -> (batch id, task)
        self._parked: set[int] = set()  # items whose transfer waits in a peer's upload queue
        self._wake = asyncio.Event()
        self._dispatcher: asyncio.Task | None = None

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Requeue items a restart interrupted and begin dispatching. Needs a running event loop."""
        reset = self.store.reset_working()
        if reset:
            logger.info("Queue: %d interrupted item(s) back to pending", reset)
        self._dispatcher = asyncio.get_running_loop().create_task(self._dispatch(), name="queue-dispatch")
        self._wake.set()

    async def stop(self) -> None:
        """Shutdown: in-flight items stay ``working`` in the store and resume on the next start."""
        tasks = [task for _, task in self._tasks.values()]
        if self._dispatcher is not None:
            tasks.append(self._dispatcher)
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    def wake(self) -> None:
        self._wake.set()

    # --------------------------------------------------------------- actions

    async def cancel_batch(self, batch_id: int) -> None:
        await asyncio.to_thread(self.store.cancel_batch, batch_id)
        tasks = [task for owner, task in self._tasks.values() if owner == batch_id]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._changed(batch_id)

    async def cancel_chat(self, chat_id: int) -> int:
        """Cancel every active batch of a chat; returns how many."""
        batches = await asyncio.to_thread(self.store.active_batches, chat_id)
        for batch in batches:
            await self.cancel_batch(batch.id)
        return len(batches)

    async def requeue(
        self, item: Item, *, forced: bool = False, pick: SearchResult | None = None, same_copy: bool = False
    ) -> None:
        """Run one item again.

        *forced* skips the owned check. *pick* fetches exactly that copy; *same_copy* keeps the
        copy picked before (a retry); with neither, the queue searches afresh.
        """
        stored = encode_pick(pick) if pick is not None else (None if same_copy else "")
        await asyncio.to_thread(self.store.requeue, item.id, forced=forced, pick=stored)
        self._changed(item.batch_id)
        self.wake()

    async def retry_failed(self, batch_id: int) -> int:
        count = await asyncio.to_thread(self.store.requeue_failed, batch_id)
        self._changed(batch_id)
        self.wake()
        return count

    # -------------------------------------------------------------- dispatch

    async def _dispatch(self) -> None:
        while True:
            while self._has_free_slot():
                item = await asyncio.to_thread(self.store.claim_next)
                if item is None:
                    break
                self._launch(item)
            await self._wake.wait()
            self._wake.clear()

    def _has_free_slot(self) -> bool:
        """A transfer waiting in a peer's upload queue does no work here, so it does not hold a slot.

        Otherwise three busy peers would stall every other search and download. MAX_PARKED bounds
        how many such transfers can pile up.
        """
        busy = len(self._tasks) - len(self._parked)
        return busy < self.workers and len(self._parked) <= MAX_PARKED

    def _launch(self, item: Item) -> None:
        task = asyncio.get_running_loop().create_task(self._work(item), name=f"queue-item-{item.id}")
        self._tasks[item.id] = (item.batch_id, task)

        def done(_task: asyncio.Task) -> None:
            self._tasks.pop(item.id, None)
            self._parked.discard(item.id)
            self.progress.pop(item.id, None)
            self._changed(item.batch_id)
            self.wake()

        task.add_done_callback(done)
        self._changed(item.batch_id)

    async def _work(self, item: Item) -> None:
        batch = await asyncio.to_thread(self.store.get_batch, item.batch_id)
        if batch is None:
            return

        def report(progress: Progress) -> None:
            self.progress[item.id] = progress
            if progress.queued != (item.id in self._parked):
                (self._parked.add if progress.queued else self._parked.discard)(item.id)
                self.wake()
            self._changed(item.batch_id)

        try:
            await self.pipeline.run(batch, item, report)
        except asyncio.CancelledError:
            raise
        except SlskdUnavailableError:
            await self._fail(item, "slskd is unreachable")
        except Exception as exc:
            logger.exception("Queue item %d (%s) failed", item.id, item.label)
            await self._fail(item, f"{type(exc).__name__}: {exc}"[:300])
        await asyncio.to_thread(self.store.close_if_finished, item.batch_id)

    async def _fail(self, item: Item, detail: str) -> None:
        await asyncio.to_thread(self.store.update_item, item.id, status=ItemStatus.failed, detail=detail)

    def _changed(self, batch_id: int) -> None:
        if self.on_change is None:
            return
        try:
            self.on_change(batch_id)
        except Exception:
            logger.exception("Queue change hook failed for batch %d", batch_id)
