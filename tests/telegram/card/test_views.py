"""Card rendering: one track, batch summary, track list, copy picker."""

from functools import partial

import pytest

from slskd_importer.queue.batch import Destination, ItemStatus
from slskd_importer.queue.copies import Copies
from slskd_importer.queue.progress import DOWNLOADING, SEARCHING, Progress
from slskd_importer.sources.tracklist import Entry
from slskd_importer.telegram.card import actions
from slskd_importer.telegram.card.item_view import render_item
from slskd_importer.telegram.card.list_view import PAGE_SIZE, render_list
from slskd_importer.telegram.card.picker_view import render_picker
from slskd_importer.telegram.card.summary_view import render_summary
from slskd_importer.telegram.i18n import t as translate
from tests.queue.helpers import make_batch, make_result, make_store, make_track

t = partial(translate, "en")


@pytest.fixture
def store(tmp_path):
    return make_store(tmp_path)


def labels(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row] if markup else []


def callbacks(markup) -> list[str]:
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def one_item(store, **fields):
    batch = make_batch(store, destination=fields.pop("destination", Destination.library))
    item = store.items(batch.id)[0]
    if fields:
        store.update_item(item.id, **fields)
    return batch, store.get_item(item.id)


def test_pending_item_offers_cancel(store):
    batch, item = one_item(store)
    text, markup = render_item(t, batch, item, None, alone=True)
    assert "*Nancy Sinatra — Bang Bang*  ·  2:42" in text and "In the queue" in text
    assert labels(markup) == ["Cancel"]


def test_downloading_item_shows_a_progress_bar(store):
    batch, item = one_item(store, status=ItemStatus.working)
    text, _ = render_item(t, batch, item, Progress(DOWNLOADING, 42.0), alone=True)
    assert "Downloading  42%" in text and "▰▰▰▰▱▱▱▱▱▱" in text
    queued, _ = render_item(t, batch, item, Progress(DOWNLOADING, 0.0, queued=True), alone=True)
    assert "Queued at the peer" in queued
    searching, _ = render_item(t, batch, item, Progress(SEARCHING), alone=True)
    assert "Searching Soulseek" in searching


def test_saved_item(store):
    batch, item = one_item(
        store, status=ItemStatus.done, saved_name="Nancy Sinatra - Bang Bang.flac", quality="FLAC · 16/44.1 · 29 MB"
    )
    text, markup = render_item(t, batch, item, None, alone=True)
    assert "Saved `Nancy Sinatra - Bang Bang.flac`" in text and "FLAC · 16/44.1 · 29 MB" in text
    assert labels(markup) == ["Other copies", "Undo", "Send file"]


def test_delivered_item_has_no_library_buttons(store):
    batch, item = one_item(store, destination=Destination.deliver, status=ItemStatus.done, quality="FLAC")
    text, markup = render_item(t, batch, item, None, alone=True)
    assert "Sent to this chat" in text
    assert labels(markup) == ["Other copies"]


@pytest.mark.parametrize(
    ("status", "words", "buttons"),
    [
        (ItemStatus.owned, "Already in your library", ["Download anyway"]),
        (ItemStatus.review, "No lossless copy. Best there is:", ["Choose a copy", "Skip"]),
        (ItemStatus.no_match, "Nothing found on Soulseek", ["Search again"]),
        (ItemStatus.failed, "Could not get it", ["Retry", "Choose a copy"]),
        (ItemStatus.removed, "Removed from the library", ["Download again"]),
        (ItemStatus.cancelled, "Cancelled", ["Download again"]),
    ],
)
def test_settled_states(store, status, words, buttons):
    batch, item = one_item(store, status=status, detail="peer_offline", saved_name="x.flac")
    text, markup = render_item(t, batch, item, None, alone=True)
    assert words in text
    assert labels(markup) == buttons
    if status in (ItemStatus.review, ItemStatus.failed):
        assert "peer\\_offline" in text  # detail is escaped for Markdown


def test_item_inside_a_batch_offers_back_not_cancel(store):
    batch, item = one_item(store)
    _, markup = render_item(t, batch, item, None, alone=False)
    assert labels(markup) == ["« Back"]


def many(store, n=12):
    batch = make_batch(store, [Entry(track=make_track(f"Song {i}")) for i in range(n)])
    return batch, store.items(batch.id)


def test_summary_counts_progress_and_attention(store):
    batch, items = many(store, 6)
    store.update_item(items[0].id, status=ItemStatus.done)
    store.update_item(items[1].id, status=ItemStatus.owned)
    store.update_item(items[2].id, status=ItemStatus.failed)
    store.update_item(items[3].id, status=ItemStatus.review)
    store.update_item(items[4].id, status=ItemStatus.working)
    items = store.items(batch.id)
    text, markup = render_summary(t, batch, items, {items[4].id: Progress(DOWNLOADING, 50.0)})
    assert text.startswith("*Test batch*\n")
    assert "4 / 6" in text
    assert (
        "✅ 1 saved" in text
        and "📀 1 already owned" in text
        and "👂 1 to review" in text
        and "❌ 1 not downloaded" in text
    )
    assert "Nancy Sinatra — Song 4  ·  50%" in text
    assert labels(markup) == [
        "❌  Nancy Sinatra — Song 2",
        "👂  Nancy Sinatra — Song 3",
        "All tracks",
        "Retry 1",
        "Cancel",
    ]


def test_finished_summary_has_no_cancel(store):
    batch, items = many(store, 2)
    for item in items:
        store.update_item(item.id, status=ItemStatus.done)
    store.close_if_finished(batch.id)
    text, markup = render_summary(t, store.get_batch(batch.id), store.items(batch.id), {})
    assert "Done  ·  2 tracks" in text
    assert labels(markup) == ["All tracks"]


def test_list_pages_and_puts_attention_first(store):
    batch, items = many(store)
    store.update_item(items[-1].id, status=ItemStatus.failed)
    text, markup = render_list(t, batch, store.items(batch.id), {}, 0)
    assert "12 tracks  ·  page 1/2" in text
    shown = labels(markup)
    assert shown[0] == "❌  Nancy Sinatra — Song 11"
    assert len(shown) == PAGE_SIZE + 2 and shown[-2:] == ["Next", "« Back"]
    _, last = render_list(t, batch, store.items(batch.id), {}, 99)
    assert labels(last)[-2:] == ["Previous", "« Back"]


def test_picker_states(store):
    batch, item = one_item(store)
    searching, _ = render_picker(t, batch, item, None, 0, 5)
    assert "Searching Soulseek" in searching
    nothing, _ = render_picker(t, batch, item, Copies(), 0, 5)
    assert "Nothing found" in nothing

    copies = Copies([make_result(i) for i in range(7)])
    text, markup = render_picker(t, batch, item, copies, 0, 5)
    assert "7 copies — choose one" in text and "*#1*  🟢  `2:42`" in text and "[FLAC]" in text
    assert labels(markup) == ["#1", "#2", "#3", "#4", "#5", "Next", "« Back"]
    assert callbacks(markup)[0] == actions.encode(actions.GET, batch.id, item.id, 0)
    _, second = render_picker(t, batch, item, copies, 1, 5)
    assert labels(second) == ["#6", "#7", "Previous", "« Back"]
    lossy, _ = render_picker(t, batch, item, Copies([make_result(0, "mp3")], lossy=True), 0, 5)
    assert "No lossless copy — 1 lossy copies" in lossy


def test_actions_round_trip():
    data = actions.encode(actions.GET, 12, 34, 5)
    assert actions.decode(data) == actions.Action(actions.GET, 12, 34, 5)
    assert len(actions.encode(actions.PICKER, 10**9, 10**9, 99)) <= 64
    assert actions.decode("lang:es") is None
    assert actions.decode("q:g:x:1:2") is None


def test_names_with_markdown_characters_stay_bold_without_backslashes(store):
    from slskd_importer.catalog.track import TrackInfo

    batch = make_batch(store, [Entry(track=TrackInfo("Isaiah", "Shake It Down [ISH_EP 04] *", "", 0, "", ""))])
    text, _ = render_item(t, batch, store.items(batch.id)[0], None, alone=True)
    assert "*Isaiah — Shake It Down [ISH EP 04]*" in text and "\\" not in text


def test_saved_item_words_the_lossless_verdict(store):
    batch, item = one_item(
        store, status=ItemStatus.done, saved_name="x.flac", quality="FLAC", detail="verdict:WARNING:19.5"
    )
    text, _ = render_item(t, batch, item, None, alone=True)
    assert "⚠️ Possible transcode · cutoff 19.5 kHz" in text
    es, _ = render_item(partial(translate, "es"), batch, item, None, alone=True)
    assert "Posible transcodificación" in es
