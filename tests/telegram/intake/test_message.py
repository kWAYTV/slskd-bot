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


def reply_to(bot, message_id: int, text: str, user_id: int = 12345):
    update = _make_update(user_id=user_id, text=text)
    update.message.reply_to_message = MagicMock(message_id=message_id)
    update.message.delete = AsyncMock()
    return update


async def test_replying_to_a_card_renames_its_track_and_searches_again(bot):
    from slskd_importer.queue.batch import ItemStatus
    from slskd_importer.queue.copies import Copies

    batch = bot.queue_store.create_batch(
        67890, 12345, "x", "track", [Entry(query="A. Morgan - Premiere: A.Morgan — Decision")], message_id=900
    )
    item = bot.queue_store.items(batch.id)[0]
    bot.queue_store.update_item(item.id, status=ItemStatus.no_match)
    bot.queue_store.save_copies(item.id, False, "[]")
    bot.runner.pipeline.finder._found[item.id] = Copies()
    bot.queue_store.close_if_finished(batch.id)

    update = reply_to(bot, 900, "A.Morgan - Decision")
    await bot.handle_text(update, context_with_card())

    again = bot.queue_store.get_item(item.id)
    assert (again.query, again.status, again.title) == ("A.Morgan - Decision", ItemStatus.pending, "")
    assert bot.queue_store.load_copies(item.id) is None and bot.runner.pipeline.finder.remembered(item.id) is None
    assert len(bot.queue_store.recent_batches(67890, 10)) == 1  # no new batch
    assert bot.queue_store.get_batch(batch.id).status == "active"
    update.message.delete.assert_awaited_once()
    bot.runner.wake.assert_called()
    assert "Searching Soulseek" in bot.telegram.edit_message_text.call_args.args[0]


async def test_reply_in_a_list_renames_the_track_on_screen_or_asks_to_open_one(bot):
    from slskd_importer.queue.batch import ItemStatus
    from slskd_importer.telegram.card import board

    batch = bot.queue_store.create_batch(
        67890, 12345, "x", "list", [Entry(query="A - B"), Entry(query="C - D")], message_id=900
    )
    first, second = bot.queue_store.items(batch.id)
    for item in (first, second):
        bot.queue_store.update_item(item.id, status=ItemStatus.choose)

    update = reply_to(bot, 900, "E - F")
    await bot.handle_text(update, context_with_card())
    update.message.reply_text.assert_awaited_once_with("Open the track on the card first, then reply to it.")
    assert bot.queue_store.get_item(first.id).query == "A - B"

    bot.cards.focus(batch.id, board.PICKER, second.id)
    await bot.handle_text(reply_to(bot, 900, "E - F"), context_with_card())
    assert bot.queue_store.get_item(second.id).query == "E - F"
    assert bot.queue_store.get_item(first.id).query == "A - B"


async def test_reply_to_a_track_in_flight_or_to_another_message(bot):
    from slskd_importer.queue.batch import ItemStatus

    batch = bot.queue_store.create_batch(67890, 12345, "x", "track", [Entry(query="A - B")], message_id=900)
    item = bot.queue_store.items(batch.id)[0]
    bot.queue_store.update_item(item.id, status=ItemStatus.working)
    update = reply_to(bot, 900, "E - F")
    await bot.handle_text(update, context_with_card())
    update.message.reply_text.assert_awaited_once()
    assert bot.queue_store.get_item(item.id).query == "A - B"

    await bot.handle_text(reply_to(bot, 555, "G - H"), context_with_card())  # not a card: an ordinary request
    await asyncio.sleep(0.05)
    assert len(bot.queue_store.recent_batches(67890, 10)) == 2
