"""The runner: dispatch, concurrency cap, failure handling, cancel, requeue, restart."""

import asyncio
from unittest.mock import MagicMock

import pytest

from slskd_importer.queue.batch import BatchStatus, ItemStatus
from slskd_importer.queue.progress import SEARCHING, Progress
from slskd_importer.queue.runner import QueueRunner
from slskd_importer.soulseek.errors import SlskdUnavailableError
from slskd_importer.sources.tracklist import Entry
from tests.queue.helpers import make_batch, make_result, make_store


class FakePipeline:
    """Finishes each item as done after an optional gate; records peak concurrency."""

    def __init__(self, store, gate: asyncio.Event | None = None, error: Exception | None = None):
        self.store = store
        self.gate = gate
        self.error = error
        self.picks = {}
        self.finder = MagicMock()
        self.running = 0
        self.peak = 0

    async def run(self, batch, item, report):
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            report(Progress(SEARCHING))
            if self.gate is not None:
                await self.gate.wait()
            if self.error is not None:
                raise self.error
            self.store.update_item(item.id, status=ItemStatus.done)
        finally:
            self.running -= 1


@pytest.fixture
def store(tmp_path):
    return make_store(tmp_path)


async def settle(store, batch_id, status=BatchStatus.done):
    for _ in range(300):
        if store.get_batch(batch_id).status == status:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"batch never became {status}: {store.counts(batch_id)}")


async def test_runs_every_item_and_closes_the_batch(store):
    batch = make_batch(store, [Entry(query=f"s{n}") for n in range(5)])
    runner = QueueRunner(store, FakePipeline(store), workers=2)
    changed = []
    runner.on_change = changed.append
    runner.start()
    await settle(store, batch.id)
    await runner.stop()
    assert store.counts(batch.id) == {"done": 5}
    assert batch.id in changed
    assert runner.progress == {}


async def test_never_exceeds_worker_count(store):
    gate = asyncio.Event()
    batch = make_batch(store, [Entry(query=f"s{n}") for n in range(6)])
    pipeline = FakePipeline(store, gate)
    runner = QueueRunner(store, pipeline, workers=2)
    runner.start()
    await asyncio.sleep(0.2)
    assert pipeline.running == 2
    assert len(runner.progress) == 2
    gate.set()
    await settle(store, batch.id)
    await runner.stop()
    assert pipeline.peak == 2


@pytest.mark.parametrize(
    ("error", "detail"),
    [(SlskdUnavailableError("down"), "slskd is unreachable"), (RuntimeError("boom"), "RuntimeError: boom")],
)
async def test_pipeline_errors_fail_the_item(store, error, detail):
    batch = make_batch(store)
    runner = QueueRunner(store, FakePipeline(store, error=error), workers=1)
    runner.start()
    await settle(store, batch.id)
    await runner.stop()
    item = store.items(batch.id)[0]
    assert item.status == ItemStatus.failed and item.detail == detail


async def test_cancel_batch_stops_in_flight_items(store):
    gate = asyncio.Event()
    batch = make_batch(store, [Entry(query="a"), Entry(query="b")])
    runner = QueueRunner(store, FakePipeline(store, gate), workers=1)
    runner.start()
    await asyncio.sleep(0.1)
    await runner.cancel_batch(batch.id)
    assert store.counts(batch.id) == {"cancelled": 2}
    assert store.get_batch(batch.id).status == BatchStatus.cancelled
    await runner.stop()


async def test_cancel_chat(store):
    make_batch(store)
    make_batch(store)
    runner = QueueRunner(store, FakePipeline(store, asyncio.Event()), workers=1)
    assert await runner.cancel_chat(67890) == 2
    assert await runner.cancel_chat(67890) == 0


async def test_requeue_with_pick_runs_the_item_again(store):
    batch = make_batch(store)
    pipeline = FakePipeline(store)
    runner = QueueRunner(store, pipeline, workers=1)
    runner.start()
    await settle(store, batch.id)
    item = store.items(batch.id)[0]
    pick = make_result(2)
    await runner.requeue(item, forced=True, pick=pick)
    assert pipeline.picks[item.id] is pick
    assert store.get_batch(batch.id).status == BatchStatus.active
    await settle(store, batch.id)
    await runner.stop()
    assert store.get_item(item.id).forced == 1


async def test_retry_failed(store):
    batch = make_batch(store)
    item = store.items(batch.id)[0]
    store.update_item(item.id, status=ItemStatus.no_match)
    store.close_if_finished(batch.id)
    runner = QueueRunner(store, FakePipeline(store), workers=1)
    runner.start()
    assert await runner.retry_failed(batch.id) == 1
    await settle(store, batch.id)
    await runner.stop()
    assert store.counts(batch.id) == {"done": 1}


async def test_stop_leaves_items_working_and_start_resumes_them(store):
    gate = asyncio.Event()
    batch = make_batch(store)
    runner = QueueRunner(store, FakePipeline(store, gate), workers=1)
    runner.start()
    await asyncio.sleep(0.1)
    await runner.stop()
    assert store.counts(batch.id) == {"working": 1}

    resumed = QueueRunner(store, FakePipeline(store), workers=1)
    resumed.start()
    await settle(store, batch.id)
    await resumed.stop()


async def test_change_hook_errors_do_not_stop_the_queue(store):
    batch = make_batch(store)
    runner = QueueRunner(store, FakePipeline(store), workers=1)
    runner.on_change = MagicMock(side_effect=RuntimeError("card broke"))
    runner.start()
    await settle(store, batch.id)
    await runner.stop()
