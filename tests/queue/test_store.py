"""Queue persistence: batches, items, fair claiming, requeue."""

import pytest

from slskd_importer.queue.batch import BatchStatus, Destination, ItemStatus
from slskd_importer.sources.tracklist import Entry
from tests.queue.helpers import make_batch, make_store, make_track


@pytest.fixture
def store(tmp_path):
    return make_store(tmp_path)


def test_create_batch_stores_items_in_order(store):
    batch = make_batch(store, [Entry(track=make_track()), Entry(query="daft punk one more time")])
    items = store.items(batch.id)
    assert [i.position for i in items] == [1, 2]
    assert items[0].identified and items[0].label == "Nancy Sinatra — Bang Bang"
    assert not items[1].identified and items[1].label == "daft punk one more time"
    assert items[1].track is None
    assert batch.to_library and batch.status == BatchStatus.active


def test_deliver_destination(store):
    batch = make_batch(store, destination=Destination.deliver)
    assert not store.get_batch(batch.id).to_library


def test_get_batch_for_chat_refuses_other_chats(store):
    batch = make_batch(store)
    assert store.get_batch_for_chat(batch.id, 67890) is not None
    assert store.get_batch_for_chat(batch.id, 1) is None


def test_claim_next_is_fair_across_batches(store):
    big = make_batch(store, [Entry(query=f"song {n}") for n in range(3)])
    small = make_batch(store, [Entry(query="one song")])
    first, second = store.claim_next(), store.claim_next()
    assert first.batch_id == big.id
    assert second.batch_id == small.id  # the batch with nothing in flight goes before big's second track
    assert store.claim_next().batch_id == big.id
    assert first.status == ItemStatus.working


def test_claim_next_empty(store):
    assert store.claim_next() is None


def test_update_item_and_counts(store):
    batch = make_batch(store, [Entry(query="a"), Entry(query="b")])
    a, b = store.items(batch.id)
    store.update_item(a.id, status=ItemStatus.done, saved_name="a.flac", quality="FLAC")
    store.update_item(b.id, status=ItemStatus.failed, detail="offline")
    assert store.counts(batch.id) == {"done": 1, "failed": 1}
    assert store.get_item(a.id).saved_name == "a.flac"
    with pytest.raises(ValueError):
        store.update_item(a.id, artist="x")


def test_set_identity(store):
    batch = make_batch(store, [Entry(query="bang bang")])
    item = store.items(batch.id)[0]
    store.set_identity(item.id, make_track())
    assert store.get_item(item.id).track == make_track()


def test_close_if_finished(store):
    batch = make_batch(store)
    item = store.items(batch.id)[0]
    assert store.close_if_finished(batch.id) is False
    store.update_item(item.id, status=ItemStatus.done)
    assert store.close_if_finished(batch.id) is True
    assert store.get_batch(batch.id).status == BatchStatus.done
    assert store.active_batches() == []


def test_cancel_batch_keeps_finished_items(store):
    batch = make_batch(store, [Entry(query="a"), Entry(query="b")])
    a, _b = store.items(batch.id)
    store.update_item(a.id, status=ItemStatus.done)
    store.cancel_batch(batch.id)
    assert store.counts(batch.id) == {"done": 1, "cancelled": 1}
    assert store.get_batch(batch.id).status == BatchStatus.cancelled


def test_requeue_reopens_batch(store):
    batch = make_batch(store)
    item = store.items(batch.id)[0]
    store.update_item(item.id, status=ItemStatus.owned)
    store.close_if_finished(batch.id)
    store.requeue(item.id, forced=True)
    again = store.get_item(item.id)
    assert again.status == ItemStatus.pending and again.forced == 1
    assert store.get_batch(batch.id).status == BatchStatus.active


def test_requeue_failed(store):
    batch = make_batch(store, [Entry(query="a"), Entry(query="b"), Entry(query="c")])
    a, b, c = store.items(batch.id)
    store.update_item(a.id, status=ItemStatus.failed)
    store.update_item(b.id, status=ItemStatus.no_match)
    store.update_item(c.id, status=ItemStatus.done)
    store.close_if_finished(batch.id)
    assert store.requeue_failed(batch.id) == 2
    assert store.counts(batch.id) == {"pending": 2, "done": 1}
    assert store.requeue_failed(batch.id) == 0


def test_reset_working(store):
    make_batch(store)
    store.claim_next()
    assert store.reset_working() == 1
    assert store.claim_next() is not None


def test_active_batches_by_chat(store):
    make_batch(store)
    assert len(store.active_batches(67890)) == 1
    assert store.active_batches(1) == []
