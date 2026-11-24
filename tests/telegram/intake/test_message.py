"""Messages in: a batch and a card per message, library or delivery by who asked."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from slskd_importer.queue.batch import Destination
from slskd_importer.sources.tracklist import Entry, SourceError, Tracklist
from slskd_importer.telegram.core.app import MusicBot
from tests.telegram.helpers import _make_config, _make_context, _make_update

INTAKE = "slskd_importer.telegram.intake.message"


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


def context_with_card():
    context = _make_context()
    context.bot.send_message.return_value = MagicMock(message_id=900, edit_text=AsyncMock())
    return context


async def send(bot, text, user_id=12345, handler="handle_text"):
    update = _make_update(user_id=user_id, text=text)
    context = context_with_card()
    await getattr(bot, handler)(update, context)
    await asyncio.sleep(0.05)
    return update, context


async def test_lines_become_one_batch_with_one_card(bot):
    _, context = await send(bot, "Nancy Sinatra - Bang Bang\ndaft punk one more time")
    (batch,) = bot.queue_store.active_batches(67890)
    assert (batch.kind, batch.message_id, batch.query_message_id) == ("list", 900, 500)
    assert batch.destination == Destination.library
    assert [i.query for i in bot.queue_store.items(batch.id)] == [
        "Nancy Sinatra - Bang Bang",
        "daft punk one more time",
    ]
    context.bot.send_message.assert_awaited_once()
    assert context.bot.send_message.call_args.kwargs["reply_parameters"].message_id == 500
    bot.runner.wake.assert_called_once()
    bot.telegram.edit_message_text.assert_awaited()


async def test_every_message_gets_its_own_batch(bot):
    await send(bot, "song one")
    await send(bot, "song two")
    assert len(bot.queue_store.active_batches(67890)) == 2


async def test_people_without_library_access_get_delivery(bot):
    bot.config.telegram_allowed_users = {12345, 222}
    bot.config.telegram_library_users = {12345}
    await send(bot, "song", user_id=222)
    (batch,) = bot.queue_store.active_batches(67890)
    assert batch.destination == Destination.deliver


async def test_unauthorized_users_queue_nothing(bot):
    update, context = await send(bot, "song", user_id=999)
    assert bot.queue_store.active_batches() == []
    context.bot.send_message.assert_not_called()


async def test_source_error_is_shown_on_the_card(bot):
    with patch(f"{INTAKE}.read_message", side_effect=SourceError("1001Tracklists blocked the request.")):
        _, context = await send(bot, "https://www.1001tracklists.com/tracklist/x")
    card = context.bot.send_message.return_value
    card.edit_text.assert_awaited_once_with("1001Tracklists blocked the request.")
    assert bot.queue_store.active_batches() == []


async def test_unexpected_error_is_reported(bot):
    with patch(f"{INTAKE}.read_message", side_effect=RuntimeError("boom")):
        _, context = await send(bot, "song")
    context.bot.send_message.return_value.edit_text.assert_awaited_once_with("That did not work. Try again.")


async def test_get_command_queues_its_argument(bot):
    source = Tracklist("Discovery", "album", "https://open.spotify.com/album/x", [Entry(query="a"), Entry(query="b")])
    with patch(f"{INTAKE}.read_message", return_value=source) as read:
        await send(bot, "/import https://open.spotify.com/album/x", handler="cmd_get")
    assert read.call_args.args[0] == "https://open.spotify.com/album/x"
    (batch,) = bot.queue_store.active_batches(67890)
    assert (batch.name, batch.kind, batch.source_url) == ("Discovery", "album", "https://open.spotify.com/album/x")


async def test_get_command_without_argument_explains(bot):
    update, _ = await send(bot, "/get", handler="cmd_get")
    update.message.reply_text.assert_awaited_once()
    assert bot.queue_store.active_batches() == []
