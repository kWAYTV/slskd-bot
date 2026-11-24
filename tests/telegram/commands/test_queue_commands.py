"""/status, /cancel, the Cancel-all button, toasts, and small UI helpers."""

from unittest.mock import AsyncMock, patch

import pytest

from slskd_importer.queue.batch import ItemStatus
from slskd_importer.sources.tracklist import Entry
from slskd_importer.telegram.card import actions
from slskd_importer.telegram.core.app import MusicBot
from slskd_importer.telegram.core.routing import toast_key
from slskd_importer.telegram.ui.formatting import clip, progress_bar
from slskd_importer.telegram.ui.reply import reply_kwargs
from tests.telegram.helpers import _make_callback_update, _make_config, _make_context, _make_update


@pytest.fixture
def bot():
    with (
        patch("slskd_importer.telegram.core.app.SpotifyResolver"),
        patch("slskd_importer.telegram.core.app.SlskdClient"),
    ):
        music_bot = MusicBot(_make_config())
    music_bot.attach(AsyncMock())
    return music_bot


def queue(bot, chat_id=67890, n=2):
    return bot.queue_store.create_batch(chat_id, 12345, "My_Set", "list", [Entry(query=f"s{i}") for i in range(n)])


async def test_status_empty(bot):
    update = _make_update()
    await bot.cmd_status(update, _make_context())
    update.message.reply_text.assert_awaited_once_with("The queue is empty.")


async def test_status_lists_only_this_chats_batches(bot):
    batch = queue(bot)
    queue(bot, chat_id=1)
    bot.queue_store.update_item(bot.queue_store.items(batch.id)[0].id, status=ItemStatus.done)
    update = _make_update()
    await bot.cmd_status(update, _make_context())
    text = update.message.reply_text.call_args.args[0]
    assert text.count("•") == 1 and "2 tracks  ·  1 / 2" in text
    markup = update.message.reply_text.call_args.kwargs["reply_markup"]
    assert [row[0].text for row in markup.inline_keyboard] == ["📍 2 tracks", "Cancel all"]


async def test_cancel_command(bot):
    batch = queue(bot)
    update = _make_update()
    await bot.cmd_cancel(update, _make_context())
    update.message.reply_text.assert_awaited_once_with("Cancelled.")
    assert bot.queue_store.get_batch(batch.id).status == "cancelled"
    await bot.cmd_cancel(update, _make_context())
    assert update.message.reply_text.call_args.args[0] == "Nothing to cancel."


async def test_cancel_all_button(bot):
    batch = queue(bot)
    update = _make_callback_update(data="cancel_all")
    await bot.handle_callback(update, _make_context())
    assert bot.queue_store.get_batch(batch.id).status == "cancelled"
    update.callback_query.edit_message_text.assert_awaited()


async def test_unknown_callback_is_ignored(bot):
    update = _make_callback_update(data="dl:1:0")
    await bot.handle_callback(update, _make_context())
    update.callback_query.answer.assert_awaited_once()


def test_toasts():
    assert toast_key(actions.encode(actions.GET, 1, 2, 3)) == "toast_downloading"
    assert toast_key(actions.encode(actions.SEND, 1, 2)) == "toast_sending"
    assert toast_key(actions.encode(actions.LIST, 1)) is None
    assert toast_key("hu:5") == "toast_removing"
    assert toast_key("lang:es") is None


def test_bot_wiring(bot):
    assert bot.runner.workers == 3
    assert bot.runner.on_change == bot.cards.request
    assert bot.runner.pipeline.deliver == bot._deliver_copy
    assert bot.locale(1) == "en"
    assert bot.set_locale(1, "es-ES") is True and bot.locale(1) == "es"
    assert bot.set_locale(1, "de") is False


def test_ui_helpers():
    assert progress_bar(50) == "▰▰▰▰▰▱▱▱▱▱"
    assert progress_bar(150) == "▰" * 10
    assert clip("short") == "short"
    assert len(clip("x" * 100)) == 64 and clip("x" * 100).endswith("…")
    assert reply_kwargs(None) == {}
    assert reply_kwargs(5)["reply_parameters"].message_id == 5


def test_stats_string_has_no_stale_placeholders(bot):
    assert "{" not in bot.t(1, "stats_totals", total=3, success=2, failed=1)


async def test_check_lists_tracks_that_are_not_what_was_asked(bot):
    from slskd_importer.catalog.track import TrackInfo

    def saved(query, artist, title, remote):
        batch = bot.queue_store.create_batch(67890, 12345, "Set", "list", [Entry(query=query)])
        item = bot.queue_store.items(batch.id)[0]
        bot.queue_store.set_identity(item.id, TrackInfo(artist, title, "", 0, "", ""))
        history_id = bot.history_repo.add(
            artist, title, f"{artist} - {title}.flac", "peer", "success", remote_path=remote, chat_id=67890
        )
        bot.queue_store.update_item(
            item.id, status=ItemStatus.done, saved_name=f"{artist} - {title}.flac", history_id=history_id
        )

    saved("Patient - Rhythm Dancer", "Vault Records", "Rhythm Dancer", "\\x\\Vault Records - Rhythm Dancer.flac")
    saved("Phil Berg - Void", "Phil Berg", "Void", "\\x\\Someone Else - Void.flac")
    saved("UMEK - Gatex", "UMEK", "Gatex", "\\UMEK\\01 Gatex.flac")

    update = _make_update()
    await bot.cmd_check(update, _make_context())
    text = update.message.reply_text.call_args.args[0]
    assert "*2 to check*  ·  of 3 recently saved" in text
    assert "`Patient - Rhythm Dancer`" in text and "`Vault Records - Rhythm Dancer.flac`" in text
    assert "`x/Someone Else - Void.flac`" in text
    assert "Gatex" not in text
    markup = update.message.reply_text.call_args.kwargs["reply_markup"]
    assert [row[0].text for row in markup.inline_keyboard] == ["🗑  Phil Berg - Void", "🗑  Patient - Rhythm Dancer"]

    wrong = next(
        i
        for b in bot.queue_store.recent_batches(67890, 10)
        for i in bot.queue_store.items(b.id)
        if i.query == "Phil Berg - Void"
    )
    with patch.object(bot.shelf, "remove", return_value=True) as remove:
        tap = _make_callback_update(data=f"cu:{wrong.id}")
        await bot.handle_callback(tap, _make_context())
    remove.assert_called_once_with("Phil Berg - Void.flac", wrong.history_id)
    assert bot.queue_store.get_item(wrong.id).status == ItemStatus.removed
    redrawn = tap.callback_query.edit_message_text.call_args.args[0]
    assert "*1 to check*" in redrawn and "Phil Berg" not in redrawn


async def test_check_when_everything_matches(bot):
    update = _make_update()
    await bot.cmd_check(update, _make_context())
    assert update.message.reply_text.call_args.args[0] == "All 0 recently saved tracks match what you asked for."


async def test_status_lists_batches_waiting_for_a_pick_and_brings_their_card_down(bot):
    batch = bot.queue_store.create_batch(67890, 12345, "Discovery", "album", [Entry(query="a"), Entry(query="b")])
    bot.queue_store.set_message(batch.id, 900)
    for item in bot.queue_store.items(batch.id):
        bot.queue_store.update_item(item.id, status=ItemStatus.choose)
    bot.queue_store.close_if_finished(batch.id)

    update = _make_update()
    await bot.cmd_status(update, _make_context())
    text = update.message.reply_text.call_args.args[0]
    assert "• Discovery  ·  👉 2 to pick" in text
    markup = update.message.reply_text.call_args.kwargs["reply_markup"]
    assert [row[0].text for row in markup.inline_keyboard] == ["📍 Discovery"]  # nothing running: no Cancel all

    tap = _make_callback_update(data=f"sb:{batch.id}")
    context = _make_context()
    context.bot.send_message.return_value.message_id = 950
    await bot.handle_callback(tap, context)
    assert bot.queue_store.get_batch(batch.id).message_id == 950
    old = context.bot.edit_message_text.call_args
    assert old.args[0] == "This card moved further down." and old.kwargs["message_id"] == 900
    assert bot.telegram.edit_message_text.call_args.kwargs["message_id"] == 950
