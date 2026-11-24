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
    assert text.count("•") == 1 and "My\\_Set  ·  1 / 2" in text
    assert update.message.reply_text.call_args.kwargs["reply_markup"] is not None


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
