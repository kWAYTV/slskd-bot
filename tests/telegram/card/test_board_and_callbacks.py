"""The card board (views, redraws, reactions) and the card buttons, against a real queue store."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import RetryAfter

from slskd_importer.queue.batch import Destination, ItemStatus
from slskd_importer.queue.copies import Copies
from slskd_importer.queue.pick import decode_pick
from slskd_importer.sources.tracklist import Entry
from slskd_importer.telegram.card import actions, board
from slskd_importer.telegram.card.board import View
from slskd_importer.telegram.card.copy_token import copy_number
from slskd_importer.telegram.core.app import MusicBot
from tests.queue.helpers import make_result, make_track
from tests.telegram.helpers import _make_callback_update, _make_config, _make_context

CHAT = 67890


@pytest.fixture
def bot():
    with (
        patch("slskd_importer.telegram.core.app.SpotifyResolver"),
        patch("slskd_importer.telegram.core.app.SlskdClient"),
    ):
        music_bot = MusicBot(_make_config())
    music_bot.attach(AsyncMock())
    music_bot.runner.wake = MagicMock()
    with patch.object(board, "TAP_GUARD_SECS", 0):
        yield music_bot


def queue(bot, n=1, **kwargs):
    entries = [Entry(track=make_track(f"Song {i}")) for i in range(n)]
    batch = bot.queue_store.create_batch(CHAT, 12345, "Set", "list", entries, message_id=900, **kwargs)
    return batch, bot.queue_store.items(batch.id)


async def press(bot, name, batch, item_id=0, number=0, user_id=12345):
    update = _make_callback_update(user_id=user_id, chat_id=CHAT, data=actions.encode(name, batch.id, item_id, number))
    await bot.handle_callback(update, _make_context())
    return update


def drawn_text(bot) -> str:
    return bot.telegram.edit_message_text.call_args.args[0]


async def test_draw_edits_once_per_change(bot):
    batch, _ = queue(bot)
    await bot.cards.draw(batch.id)
    await bot.cards.draw(batch.id)
    assert bot.telegram.edit_message_text.await_count == 1
    assert bot.telegram.edit_message_text.call_args.kwargs["message_id"] == 900
    assert "Nancy Sinatra — Song 0" in drawn_text(bot)


async def test_request_collapses_bursts(bot):
    batch, _ = queue(bot)
    with patch.object(board, "REDRAW_INTERVAL_SECS", 0.01):
        for _ in range(5):
            bot.cards.request(batch.id)
        await asyncio.sleep(0.1)
    assert bot.telegram.edit_message_text.await_count == 1


async def test_flood_control_marks_the_card_dirty(bot):
    batch, _ = queue(bot)
    bot.telegram.edit_message_text.side_effect = RetryAfter(0)
    await bot.cards.draw(batch.id)
    assert batch.id in bot.cards._dirty


async def test_finished_batch_reacts_on_the_request(bot):
    batch, items = queue(bot, query_message_id=500)
    bot.queue_store.update_item(items[0].id, status=ItemStatus.done, saved_name="x.flac")
    bot.queue_store.close_if_finished(batch.id)
    await bot.cards.draw(batch.id)
    await bot.cards.draw(batch.id)
    bot.telegram.set_message_reaction.assert_awaited_once()
    assert bot.telegram.set_message_reaction.call_args.kwargs["message_id"] == 500


async def test_views_switch_between_summary_list_and_item(bot):
    batch, items = queue(bot, 3)
    await bot.cards.draw(batch.id)
    assert "0 / 3" in drawn_text(bot)
    await press(bot, actions.LIST, batch)
    assert "3 tracks  ·  page 1/1" in drawn_text(bot)
    await press(bot, actions.ITEM, batch, items[1].id)
    assert "Song 1" in drawn_text(bot) and "In the queue" in drawn_text(bot)
    await press(bot, actions.SUMMARY, batch)
    assert "0 / 3" in drawn_text(bot)


async def test_buttons_cannot_reach_another_chats_batch(bot):
    batch, _ = queue(bot)
    update = _make_callback_update(chat_id=1, data=actions.encode(actions.CANCEL, batch.id))
    await bot.handle_callback(update, _make_context())
    assert bot.queue_store.get_batch(batch.id).status == "active"


async def test_unauthorized_taps_are_ignored(bot):
    batch, _ = queue(bot)
    await press(bot, actions.CANCEL, batch, user_id=999)
    assert bot.queue_store.get_batch(batch.id).status == "active"


async def test_cancel(bot):
    batch, _ = queue(bot, 2)
    update = await press(bot, actions.CANCEL, batch)
    assert bot.queue_store.counts(batch.id) == {"cancelled": 2}
    assert update.callback_query.answer.call_args.kwargs["text"] == "Cancelled"


async def test_retry_failed(bot):
    batch, items = queue(bot, 2)
    bot.queue_store.update_item(items[0].id, status=ItemStatus.failed)
    bot.queue_store.update_item(items[1].id, status=ItemStatus.done)
    await press(bot, actions.RETRY_FAILED, batch)
    assert bot.queue_store.counts(batch.id) == {"pending": 1, "done": 1}
    bot.runner.wake.assert_called()


async def test_picker_searches_then_get_requeues_with_the_pick(bot):
    batch, items = queue(bot)
    item = items[0]
    bot.queue_store.update_item(item.id, status=ItemStatus.review)
    copies = Copies([make_result(0), make_result(1)])
    finder = bot.runner.pipeline.finder

    async def find(item_id, track):
        finder._found[item_id] = copies
        return copies

    with patch.object(finder, "find", AsyncMock(side_effect=find)) as search:
        await press(bot, actions.PICKER, batch, item.id)
        await press(bot, actions.PICKER, batch, item.id)
    search.assert_awaited_once()
    assert "2 copies — choose one" in drawn_text(bot)

    await press(bot, actions.GET, batch, item.id, copy_number(1, copies.ranked[1]))
    again = bot.queue_store.get_item(item.id)
    assert decode_pick(again.pick) == copies.ranked[1]
    assert again.status == ItemStatus.pending and again.forced == 1


async def test_get_replaces_a_saved_track(bot):
    batch, items = queue(bot)
    item = items[0]
    bot.queue_store.update_item(item.id, status=ItemStatus.done, saved_name="old.flac", history_id=3)
    bot.runner.pipeline.finder._found[item.id] = Copies([make_result(0)])
    with patch.object(bot.shelf, "remove", MagicMock(return_value=True)) as remove:
        await press(bot, actions.GET, batch, item.id, copy_number(0, make_result(0)))
    remove.assert_not_called()  # the old file stays until the new copy has landed
    again = bot.queue_store.get_item(item.id)
    assert (again.saved_name, again.history_id, bool(again.pick)) == ("old.flac", 3, True)


async def test_get_ignores_a_stale_index(bot):
    batch, items = queue(bot)
    bot.queue_store.update_item(items[0].id, status=ItemStatus.failed)
    bot.runner.pipeline.finder._found[items[0].id] = Copies([make_result(0)])
    await press(bot, actions.GET, batch, items[0].id, 9)
    assert bot.queue_store.get_item(items[0].id).status == ItemStatus.failed


async def test_undo_removes_the_save(bot):
    batch, items = queue(bot)
    bot.queue_store.update_item(items[0].id, status=ItemStatus.done, saved_name="x.flac", history_id=3)
    with patch.object(bot.shelf, "remove", MagicMock(return_value=True)) as remove:
        await press(bot, actions.UNDO, batch, items[0].id)
    remove.assert_called_once_with("x.flac", 3)
    assert bot.queue_store.get_item(items[0].id).status == ItemStatus.removed


async def test_undo_needs_library_access(bot):
    bot.config.telegram_library_users = {1}
    batch, items = queue(bot)
    bot.queue_store.update_item(items[0].id, status=ItemStatus.done, saved_name="x.flac")
    with patch.object(bot.shelf, "remove", MagicMock()) as remove:
        await press(bot, actions.UNDO, batch, items[0].id)
    remove.assert_not_called()


async def test_send_file(bot, tmp_path):
    batch, items = queue(bot)
    saved = tmp_path / "x.flac"
    saved.write_bytes(b"audio")
    bot.queue_store.update_item(items[0].id, status=ItemStatus.done, saved_name="x.flac", quality="FLAC")
    with patch.object(bot.shelf, "path_of", return_value=str(saved)):
        await press(bot, actions.SEND, batch, items[0].id)
    bot.telegram.send_audio.assert_awaited_once()
    assert bot.telegram.send_audio.call_args.kwargs["filename"] == "x.flac"


async def test_again_and_retry(bot):
    batch, items = queue(bot, 2)
    bot.queue_store.update_item(items[0].id, status=ItemStatus.owned)
    bot.queue_store.update_item(items[1].id, status=ItemStatus.no_match)
    await press(bot, actions.AGAIN, batch, items[0].id)
    await press(bot, actions.RETRY, batch, items[1].id)
    first, second = bot.queue_store.items(batch.id)
    assert (first.status, first.forced) == (ItemStatus.pending, 1)
    assert (second.status, second.forced) == (ItemStatus.pending, 0)


async def test_deliver_copy_sends_to_the_batch_chat(bot, tmp_path):
    batch, items = queue(bot, destination=Destination.deliver)
    path = tmp_path / "landed.flac"
    path.write_bytes(b"audio")
    sent = await bot._deliver_copy(batch, items[0], make_track(), make_result(), str(path), "FLAC · 29 MB")
    assert sent is True
    kwargs = bot.telegram.send_audio.call_args.kwargs
    assert kwargs["chat_id"] == CHAT and kwargs["filename"] == "Nancy Sinatra - Bang Bang.flac"
    assert kwargs["caption"] == "Nancy Sinatra — Bang Bang\nFLAC · 29 MB"


def test_view_defaults():
    assert View() == View(board.SUMMARY, 0, 0)


async def test_skip_leaves_a_track_waiting_for_review(bot):
    batch, items = queue(bot)
    bot.queue_store.update_item(items[0].id, status=ItemStatus.review, detail="MP3 · 320k · 13 MB")
    await press(bot, actions.SKIP, batch, items[0].id)
    assert bot.queue_store.get_item(items[0].id).status == ItemStatus.cancelled
    assert "Cancelled." in drawn_text(bot)


async def test_skip_clears_unfound_and_failed_tracks_from_the_summary(bot):
    batch, items = queue(bot, 3)
    bot.queue_store.update_item(items[0].id, status=ItemStatus.no_match)
    bot.queue_store.update_item(items[1].id, status=ItemStatus.failed)
    bot.queue_store.update_item(items[2].id, status=ItemStatus.done)
    await press(bot, actions.SKIP, batch, items[0].id)
    await press(bot, actions.SKIP, batch, items[1].id)
    await press(bot, actions.SKIP, batch, items[2].id)  # a saved track is not skippable
    assert bot.queue_store.counts(batch.id) == {"cancelled": 2, "done": 1}


async def test_single_song_card_opens_on_its_copies_and_a_pick_fetches(bot):
    batch = bot.queue_store.create_batch(CHAT, 12345, "Bang Bang", "track", [Entry(track=make_track())], message_id=900)
    item = bot.queue_store.items(batch.id)[0]
    bot.queue_store.update_item(item.id, status=ItemStatus.choose)
    bot.runner.pipeline.finder._found[item.id] = Copies([make_result(0), make_result(1)])
    await bot.cards.draw(batch.id)
    assert "2 copies — choose one" in drawn_text(bot)

    await press(bot, actions.ITEM, batch, item.id)  # Back from the picker
    assert "Which copy do you want?" in drawn_text(bot)

    await press(bot, actions.GET, batch, item.id, copy_number(1, make_result(1)))
    assert bot.queue_store.get_item(item.id).status == ItemStatus.pending
    assert decode_pick(bot.queue_store.get_item(item.id).pick).username == "user1"


async def test_single_song_without_remembered_copies_offers_to_choose(bot):
    batch = bot.queue_store.create_batch(CHAT, 12345, "Bang Bang", "track", [Entry(track=make_track())], message_id=900)
    item = bot.queue_store.items(batch.id)[0]
    bot.queue_store.update_item(item.id, status=ItemStatus.choose)
    await bot.cards.draw(batch.id)  # after a restart nothing is remembered
    assert "Which copy do you want?" in drawn_text(bot)
    await press(bot, actions.SKIP, batch, item.id)
    assert bot.queue_store.get_item(item.id).status == ItemStatus.cancelled


def back_button(bot) -> str:
    markup = bot.telegram.edit_message_text.call_args.kwargs["reply_markup"]
    return markup.inline_keyboard[-1][0].callback_data


async def test_back_returns_to_where_the_track_was_opened_from(bot):
    batch, items = queue(bot, 12)
    bot.queue_store.update_item(items[0].id, status=ItemStatus.failed)
    bot.runner.pipeline.finder._found[items[0].id] = Copies([make_result(0)])

    await press(bot, actions.ITEM, batch, items[0].id)  # from the summary
    assert back_button(bot) == actions.encode(actions.SUMMARY, batch.id)
    await press(bot, actions.PICKER, batch, items[0].id)
    await press(bot, actions.ITEM, batch, items[0].id)  # the picker's Back
    assert back_button(bot) == actions.encode(actions.SUMMARY, batch.id)

    await press(bot, actions.LIST, batch, 0, 1)
    await press(bot, actions.ITEM, batch, items[5].id)  # from page 2 of the list
    assert back_button(bot) == actions.encode(actions.LIST, batch.id, 0, 1)


async def test_acting_on_a_track_returns_to_the_summary(bot):
    batch, items = queue(bot, 3)
    bot.queue_store.update_item(items[0].id, status=ItemStatus.choose)
    bot.queue_store.update_item(items[1].id, status=ItemStatus.no_match)
    bot.runner.pipeline.finder._found[items[0].id] = Copies([make_result(0)])

    await press(bot, actions.PICKER, batch, items[0].id)  # tapped on the summary
    assert "1 copies — choose one" in drawn_text(bot)
    assert back_button(bot) == actions.encode(actions.SUMMARY, batch.id)
    await press(bot, actions.GET, batch, items[0].id, copy_number(0, make_result(0)))
    assert "/ 3" in drawn_text(bot)  # the summary again, no Back needed

    await press(bot, actions.ITEM, batch, items[1].id)
    await press(bot, actions.SKIP, batch, items[1].id)
    assert "/ 3" in drawn_text(bot)


async def test_track_waiting_for_a_pick_in_a_list_opens_on_its_copies(bot):
    batch, items = queue(bot, 3)
    bot.queue_store.update_item(items[1].id, status=ItemStatus.choose)
    bot.runner.pipeline.finder._found[items[1].id] = Copies([make_result(0), make_result(1)])
    await bot.cards.draw(batch.id)
    assert "👉 1 to pick" in drawn_text(bot)
    markup = bot.telegram.edit_message_text.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == actions.encode(actions.TOUR, batch.id)
    assert markup.inline_keyboard[1][0].callback_data == actions.encode(actions.PICKER, batch.id, items[1].id)
    await press(bot, actions.PICKER, batch, items[1].id)
    assert "2 copies — choose one" in drawn_text(bot)


async def test_doubted_copy_shows_on_the_summary_and_can_be_kept(bot):
    batch, items = queue(bot, 3)
    bot.queue_store.update_item(
        items[0].id, status=ItemStatus.doubt, saved_name="x.flac", quality="FLAC", detail="verdict:SUSPICIOUS:17.8"
    )
    await bot.cards.draw(batch.id)
    assert "👂 1 to review" in drawn_text(bot)
    markup = bot.telegram.edit_message_text.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].text == "⚠️  Nancy Sinatra — Song 0"

    await press(bot, actions.ITEM, batch, items[0].id)
    text = drawn_text(bot)
    assert "Likely transcode · cutoff 17.8 kHz" in text and "Keep it, or pick another?" in text
    markup = bot.telegram.edit_message_text.call_args.kwargs["reply_markup"]
    assert [button.text for button in markup.inline_keyboard[0]] == ["Keep", "Other copies", "Undo"]

    await press(bot, actions.KEEP, batch, items[0].id)
    assert bot.queue_store.get_item(items[0].id).status == ItemStatus.done
    assert "/ 3" in drawn_text(bot)  # back on the summary


async def test_doubted_copy_can_be_undone_or_replaced(bot):
    batch, items = queue(bot, 2)
    for item in items:
        bot.queue_store.update_item(item.id, status=ItemStatus.doubt, saved_name="x.flac", history_id=3)
    bot.runner.pipeline.finder._found[items[1].id] = Copies([make_result(0)])
    with patch.object(bot.shelf, "remove", MagicMock(return_value=True)) as remove:
        await press(bot, actions.UNDO, batch, items[0].id)
        await press(bot, actions.GET, batch, items[1].id, copy_number(0, make_result(0)))
    remove.assert_called_once_with("x.flac", 3)
    assert bot.queue_store.get_item(items[0].id).status == ItemStatus.removed
    assert bot.queue_store.get_item(items[1].id).pick


async def test_going_through_the_waiting_tracks_one_after_another(bot):
    batch, items = queue(bot, 4)
    for item in items[:3]:
        bot.queue_store.update_item(item.id, status=ItemStatus.choose)
        bot.runner.pipeline.finder._found[item.id] = Copies([make_result(item.position)])
    bot.queue_store.update_item(items[3].id, status=ItemStatus.done)
    bot.queue_store.close_if_finished(batch.id)

    await press(bot, actions.TOUR, batch)
    assert "Song 0" in drawn_text(bot) and "👉 Left to pick: 3" in drawn_text(bot)

    await press(bot, actions.GET, batch, items[0].id, copy_number(0, make_result(1)))
    assert bot.queue_store.get_item(items[0].id).status == ItemStatus.pending
    assert "Song 1" in drawn_text(bot) and "👉 Left to pick: 2" in drawn_text(bot)  # straight on to the next

    await press(bot, actions.SKIP, batch, items[1].id)
    assert "Song 2" in drawn_text(bot) and "👉 Left to pick: 1" in drawn_text(bot)

    await press(bot, actions.GET, batch, items[2].id, copy_number(0, make_result(3)))
    assert "/ 4" in drawn_text(bot)  # nothing left: back on the summary


async def test_double_tap_does_not_pick_for_the_next_track(bot):
    batch, items = queue(bot, 2)
    for item in items:
        bot.queue_store.update_item(item.id, status=ItemStatus.choose)
        bot.runner.pipeline.finder._found[item.id] = Copies([make_result(0)])
    await press(bot, actions.TOUR, batch)
    with patch.object(board, "TAP_GUARD_SECS", 60):
        await press(bot, actions.GET, batch, items[0].id, copy_number(0, make_result(0)))
    assert bot.queue_store.get_item(items[0].id).status == ItemStatus.choose  # too soon after it came on screen


async def test_a_copy_button_from_an_old_list_fetches_nothing(bot):
    batch, items = queue(bot)
    bot.queue_store.update_item(items[0].id, status=ItemStatus.choose)
    stale = copy_number(0, make_result(7))
    bot.runner.pipeline.finder._found[items[0].id] = Copies([make_result(0)])  # searched again since
    await press(bot, actions.GET, batch, items[0].id, stale)
    assert bot.queue_store.get_item(items[0].id).status == ItemStatus.choose


async def test_skip_all_lets_go_of_waiting_tracks_only(bot):
    batch, items = queue(bot, 4)
    bot.queue_store.update_item(items[0].id, status=ItemStatus.choose)
    bot.queue_store.update_item(items[1].id, status=ItemStatus.review)
    bot.queue_store.update_item(items[2].id, status=ItemStatus.doubt, saved_name="x.flac")
    bot.queue_store.update_item(items[3].id, status=ItemStatus.done)
    await press(bot, actions.SKIP_ALL, batch)
    assert bot.queue_store.counts(batch.id) == {"cancelled": 2, "doubt": 1, "done": 1}


async def test_summary_stays_within_a_message_with_many_tracks_in_flight(bot):
    from slskd_importer.queue.progress import DOWNLOADING, SEARCHING, Progress

    batch, items = queue(bot, 80)
    for item in items[:70]:
        bot.queue_store.update_item(item.id, status=ItemStatus.working)
        queued = item.position > 8
        bot.runner.progress[item.id] = Progress(DOWNLOADING if queued else SEARCHING, 0.0, queued=queued)
    await bot.cards.draw(batch.id)
    text = drawn_text(bot)
    assert len(text) < 1000
    assert "… and 3 more" in text and "⌛ 62 waiting in peer queues" in text


async def test_waiting_batch_says_so_instead_of_done(bot):
    batch, items = queue(bot, 2, query_message_id=500)
    bot.queue_store.update_item(items[0].id, status=ItemStatus.choose)
    bot.queue_store.update_item(items[1].id, status=ItemStatus.done)
    bot.queue_store.close_if_finished(batch.id)
    await bot.cards.draw(batch.id)
    assert "👉 Waiting for your pick: 1" in drawn_text(bot) and "Done" not in drawn_text(bot)
    bot.telegram.set_message_reaction.assert_awaited_once()  # 👍: one track did arrive
