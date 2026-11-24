"""One item through the pipeline: owned, no match, lossy review, fake gate, save, deliver, picks."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from slskd_importer.queue.batch import Destination, ItemStatus
from slskd_importer.queue.copies import Copies
from slskd_importer.queue.fetch import Landed
from slskd_importer.queue.pipeline import ItemPipeline, describe_copy
from slskd_importer.queue.shelf import Placed
from slskd_importer.sources.tracklist import Entry
from tests.queue.helpers import make_batch, make_result, make_store, make_track

PIPELINE = "slskd_importer.queue.pipeline"


@pytest.fixture
def store(tmp_path):
    return make_store(tmp_path)


def make_pipeline(store, ranked=None, lossy=False, owned=None, auto_pick=True):
    finder = MagicMock()
    finder.find = AsyncMock(return_value=Copies(ranked if ranked is not None else [make_result()], lossy))
    shelf = MagicMock()
    shelf.owned_as.return_value = owned
    shelf.place = AsyncMock(return_value=Placed("Nancy Sinatra - Bang Bang.flac", 7))
    return ItemPipeline(
        config=SimpleNamespace(download_timeout_secs=5, auto_pick=auto_pick),
        spotify=MagicMock(),
        slskd=MagicMock(),
        processor=MagicMock(),
        store=store,
        finder=finder,
        shelf=shelf,
    )


async def run(pipeline, store, batch):
    item = store.items(batch.id)[0]
    await pipeline.run(batch, item, lambda progress: None)
    return store.get_item(item.id)


def landed(path="/downloads/x.flac"):
    return AsyncMock(return_value=Landed(path=path, transfer_id="t1"))


def verdict(kind="AUTHENTIC"):
    return MagicMock(return_value=SimpleNamespace(verdict=kind, cutoff_khz=15.2, display=f"{kind} display"))


def test_describe_copy():
    assert describe_copy(make_result()) == "FLAC · 16/44.1 · 29 MB"


async def test_owned_track_is_not_fetched(store):
    pipeline = make_pipeline(store, owned="Nancy Sinatra - Bang Bang.flac")
    item = await run(pipeline, store, make_batch(store))
    assert item.status == ItemStatus.owned
    assert item.saved_name == "Nancy Sinatra - Bang Bang.flac"
    pipeline.finder.find.assert_not_called()


async def test_no_match(store):
    item = await run(make_pipeline(store, ranked=[]), store, make_batch(store))
    assert item.status == ItemStatus.no_match


async def test_only_lossy_goes_to_review(store):
    pipeline = make_pipeline(store, ranked=[make_result(extension="mp3")], lossy=True)
    item = await run(pipeline, store, make_batch(store))
    assert item.status == ItemStatus.review
    assert item.detail == "MP3 · 16/44.1 · 29 MB"


async def test_saves_best_copy(store):
    pipeline = make_pipeline(store)
    with (
        patch(f"{PIPELINE}.fetch", landed()),
        patch(f"{PIPELINE}.discard", AsyncMock()) as discard,
        patch(f"{PIPELINE}.analyze_lossless", verdict()),
    ):
        item = await run(pipeline, store, make_batch(store))
    assert item.status == ItemStatus.done
    assert item.saved_name == "Nancy Sinatra - Bang Bang.flac"
    assert item.history_id == 7
    assert item.quality.startswith("FLAC")
    assert item.detail == "verdict:AUTHENTIC:15.2"
    discard.assert_awaited_once()


async def test_fake_lossless_is_skipped_for_the_next_copy(store):
    pipeline = make_pipeline(store, ranked=[make_result(0), make_result(1)])
    verdicts = MagicMock(
        side_effect=[
            SimpleNamespace(verdict="FAKE", cutoff_khz=15.2, display="fake"),
            SimpleNamespace(verdict="AUTHENTIC", cutoff_khz=21.9, display="ok"),
        ]
    )
    with (
        patch(f"{PIPELINE}.fetch", landed()) as fetch,
        patch(f"{PIPELINE}.discard", AsyncMock()),
        patch(f"{PIPELINE}.analyze_lossless", verdicts),
    ):
        item = await run(pipeline, store, make_batch(store))
    assert item.status == ItemStatus.done
    assert fetch.await_count == 2


async def test_every_copy_failing_fails_the_item(store):
    pipeline = make_pipeline(store, ranked=[make_result(0), make_result(1)])
    with patch(f"{PIPELINE}.fetch", AsyncMock(return_value=Landed(error="timed out"))):
        item = await run(pipeline, store, make_batch(store))
    assert item.status == ItemStatus.failed
    assert item.detail == "timed out; timed out"


async def test_picked_copy_is_trusted_and_skips_search(store):
    pipeline = make_pipeline(store, owned="already.flac")
    batch = make_batch(store)
    item = store.items(batch.id)[0]
    pipeline.picks[item.id] = make_result(3, "mp3")
    with (
        patch(f"{PIPELINE}.fetch", landed("/downloads/x.mp3")) as fetch,
        patch(f"{PIPELINE}.discard", AsyncMock()),
    ):
        done = await run(pipeline, store, batch)
    assert done.status == ItemStatus.done
    assert fetch.await_args.args[2].username == "user3"
    pipeline.finder.find.assert_not_called()
    assert pipeline.picks == {}


async def test_deliver_sends_and_never_places(store):
    pipeline = make_pipeline(store, owned="mine.flac")
    pipeline.deliver = AsyncMock(return_value=True)
    batch = make_batch(store, destination=Destination.deliver)
    with (
        patch(f"{PIPELINE}.fetch", landed()),
        patch(f"{PIPELINE}.discard", AsyncMock()) as discard,
        patch(f"{PIPELINE}.analyze_lossless", verdict()),
    ):
        item = await run(pipeline, store, batch)
    assert item.status == ItemStatus.done and item.saved_name == ""
    pipeline.deliver.assert_awaited_once()
    pipeline.shelf.place.assert_not_called()
    pipeline.shelf.owned_as.assert_not_called()
    pipeline.shelf.record.assert_called_once()
    assert pipeline.shelf.record.call_args.args[2] == "delivered"
    discard.assert_awaited_once()


async def test_failed_delivery_fails_the_item(store):
    pipeline = make_pipeline(store)
    pipeline.deliver = AsyncMock(return_value=False)
    with (
        patch(f"{PIPELINE}.fetch", landed()),
        patch(f"{PIPELINE}.discard", AsyncMock()),
        patch(f"{PIPELINE}.analyze_lossless", verdict()),
    ):
        item = await run(pipeline, store, make_batch(store, destination=Destination.deliver))
    assert item.status == ItemStatus.failed


async def test_unidentified_item_is_looked_up_and_stored(store):
    pipeline = make_pipeline(store, ranked=[])
    with patch(f"{PIPELINE}.identify", MagicMock(return_value=make_track())) as identify:
        item = await run(pipeline, store, make_batch(store, [Entry(query="bang bang")]))
    identify.assert_called_once()
    assert item.track == make_track()


async def test_cancel_after_landing_discards_the_file(store):
    pipeline = make_pipeline(store)
    pipeline.shelf.place = AsyncMock(side_effect=asyncio.CancelledError)
    with (
        patch(f"{PIPELINE}.fetch", landed()),
        patch(f"{PIPELINE}.discard", AsyncMock()) as discard,
        patch(f"{PIPELINE}.analyze_lossless", verdict()),
        pytest.raises(asyncio.CancelledError),
    ):
        await run(pipeline, store, make_batch(store))
    discard.assert_awaited()


async def test_two_items_wanting_the_same_remote_file_take_turns(store):
    pipeline = make_pipeline(store)
    pipeline.deliver = AsyncMock(return_value=True)
    in_flight = peak = 0

    async def slow_fetch(*args, **kwargs):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.02)
        return Landed(path="/downloads/x.flac", transfer_id="t1")

    async def slow_discard(*args):
        nonlocal in_flight
        await asyncio.sleep(0.02)
        in_flight -= 1

    mine, theirs = make_batch(store), make_batch(store, destination=Destination.deliver)
    with (
        patch(f"{PIPELINE}.fetch", slow_fetch),
        patch(f"{PIPELINE}.discard", slow_discard),
        patch(f"{PIPELINE}.analyze_lossless", verdict()),
    ):
        results = await asyncio.gather(run(pipeline, store, mine), run(pipeline, store, theirs))
    assert [item.status for item in results] == [ItemStatus.done, ItemStatus.done]
    assert peak == 1
    assert pipeline._copy_locks == {}


async def test_replaced_file_is_removed_only_once_the_new_copy_is_ready(store):
    pipeline = make_pipeline(store)
    batch = make_batch(store)
    item = store.items(batch.id)[0]
    pipeline.picks[item.id] = make_result(1)
    pipeline.replaces[item.id] = ("old.flac", 3)
    with patch(f"{PIPELINE}.fetch", AsyncMock(return_value=Landed(error="timed out"))):
        failed = await run(pipeline, store, batch)
    assert failed.status == ItemStatus.failed
    pipeline.shelf.remove.assert_not_called()

    pipeline.picks[item.id] = make_result(1)
    pipeline.replaces[item.id] = ("old.flac", 3)
    with (
        patch(f"{PIPELINE}.fetch", landed()),
        patch(f"{PIPELINE}.discard", AsyncMock()),
        patch(f"{PIPELINE}.analyze_lossless", verdict()),
    ):
        done = await run(pipeline, store, batch)
    assert done.status == ItemStatus.done
    pipeline.shelf.remove.assert_called_once_with("old.flac", 3)


async def test_a_song_asked_for_on_its_own_waits_for_a_pick(store):
    pipeline = make_pipeline(store)
    batch = store.create_batch(67890, 12345, "Bang Bang", "track", [Entry(track=make_track())], message_id=900)
    with patch(f"{PIPELINE}.fetch", landed()) as fetch:
        item = await run(pipeline, store, batch)
    assert item.status == ItemStatus.choose
    fetch.assert_not_called()


async def test_only_hand_picked_copies_wait_out_a_peer_queue(store):
    pipeline = make_pipeline(store)
    with (
        patch(f"{PIPELINE}.fetch", landed()) as fetch,
        patch(f"{PIPELINE}.discard", AsyncMock()),
        patch(f"{PIPELINE}.analyze_lossless", verdict()),
    ):
        await run(pipeline, store, make_batch(store))
        assert fetch.await_args.kwargs["queue_patience_secs"] == 90
        batch = make_batch(store)
        pipeline.picks[store.items(batch.id)[0].id] = make_result(1)
        await run(pipeline, store, batch)
        assert fetch.await_args.kwargs["queue_patience_secs"] is None


async def test_without_auto_pick_every_list_track_waits_for_a_pick(store):
    pipeline = make_pipeline(store, auto_pick=False)
    with patch(f"{PIPELINE}.fetch", landed()) as fetch:
        item = await run(pipeline, store, make_batch(store))
    assert item.status == ItemStatus.choose
    fetch.assert_not_called()
