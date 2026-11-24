"""The card board (views, redraws, reactions) and the card buttons, against a real queue store."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import RetryAfter

from slskd_importer.queue.batch import Destination, ItemStatus
from slskd_importer.queue.copies import Copies
from slskd_importer.sources.tracklist import Entry
from slskd_importer.telegram.card import actions, board
from slskd_importer.telegram.card.board import View
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
    return music_bot


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

    await press(bot, actions.GET, batch, item.id, 1)
    assert bot.runner.pipeline.picks[item.id] is copies.ranked[1]
    again = bot.queue_store.get_item(item.id)
    assert again.status == ItemStatus.pending and again.forced == 1


async def test_get_replaces_a_saved_track(bot):
    batch, items = queue(bot)
    item = items[0]
    bot.queue_store.update_item(item.id, status=ItemStatus.done, saved_name="old.flac", history_id=3)
    bot.runner.pipeline.finder._found[item.id] = Copies([make_result(0)])
    with patch.object(bot.shelf, "remove", MagicMock(return_value=True)) as remove:
        await press(bot, actions.GET, batch, item.id, 0)
    remove.assert_not_called()  # the old file stays until the new copy has landed
    assert bot.runner.pipeline.replaces[item.id] == ("old.flac", 3)


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

    await press(bot, actions.GET, batch, item.id, 1)
    assert bot.queue_store.get_item(item.id).status == ItemStatus.pending
    assert bot.runner.pipeline.picks[item.id].username == "user1"


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
    await press(bot, actions.GET, batch, items[0].id, 0)
    assert "/ 3" in drawn_text(bot)  # the summary again, no Back needed

    await press(bot, actions.ITEM, batch, items[1].id)
    await press(bot, actions.SKIP, batch, items[1].id)
    assert "/ 3" in drawn_text(bot)


async def test_track_waiting_for_a_pick_in_a_list_opens_on_its_copies(bot):
    batch, items = queue(bot, 3)
    bot.queue_store.update_item(items[1].id, status=ItemStatus.choose)
    bot.runner.pipeline.finder._found[items[1].id] = Copies([make_result(0), make_result(1)])
    await bot.cards.draw(batch.id)
    assert "👂 1 to review" in drawn_text(bot)
    markup = bot.telegram.edit_message_text.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].callback_data == actions.encode(actions.PICKER, batch.id, items[1].id)
    await press(bot, actions.PICKER, batch, items[1].id)
    assert "2 copies — choose one" in drawn_text(bot)
