"""Sending files: audio, document fallback, flood control, OGG for oversize files."""

from unittest.mock import AsyncMock, patch

import pytest
from telegram.error import BadRequest, RetryAfter

from slskd_importer.telegram.delivery.send import Audio, flood_wait_secs, send_file

SEND = "slskd_importer.telegram.delivery.send"
AUDIO = Audio("Artist - Title.flac", "Title", "Artist", 200, "Artist — Title")


@pytest.fixture
def path(tmp_path):
    file = tmp_path / "x.flac"
    file.write_bytes(b"x" * 100)
    return str(file)


async def send(bot, path, limit=1000):
    return await send_file(bot, 1, path, AUDIO, file_limit=limit, oversize_note="OGG copy", reply_to=900)


async def test_sends_as_audio(path):
    bot = AsyncMock()
    assert await send(bot, path) is True
    kwargs = bot.send_audio.call_args.kwargs
    assert (kwargs["filename"], kwargs["title"], kwargs["performer"]) == ("Artist - Title.flac", "Title", "Artist")
    assert kwargs["reply_parameters"].message_id == 900
    bot.send_document.assert_not_called()


async def test_falls_back_to_document(path):
    bot = AsyncMock()
    bot.send_audio.side_effect = BadRequest("unsupported")
    assert await send(bot, path) is True
    bot.send_document.assert_awaited_once()


async def test_flood_control_waits_and_retries_as_audio(path):
    bot = AsyncMock()
    bot.send_audio.side_effect = [BadRequest("Too Many Requests: retry after 3"), None]
    with patch(f"{SEND}.asyncio.sleep", AsyncMock()) as sleep:
        assert await send(bot, path) is True
    sleep.assert_awaited_once_with(3.5)
    assert bot.send_audio.await_count == 2
    bot.send_document.assert_not_called()


async def test_oversize_goes_as_ogg(path, tmp_path):
    ogg = tmp_path / "converted.ogg"
    ogg.write_bytes(b"o" * 10)
    bot = AsyncMock()
    with patch(f"{SEND}.convert_to_ogg", return_value=str(ogg)):
        assert await send(bot, path, limit=50) is True
    kwargs = bot.send_audio.call_args.kwargs
    assert kwargs["filename"] == "Artist - Title.ogg"
    assert kwargs["caption"] == "Artist — Title\nOGG copy"
    assert not ogg.exists()


async def test_oversize_that_cannot_be_converted_or_still_too_big(path, tmp_path):
    bot = AsyncMock()
    with patch(f"{SEND}.convert_to_ogg", return_value=None):
        assert await send(bot, path, limit=50) is False
    ogg = tmp_path / "big.ogg"
    ogg.write_bytes(b"o" * 80)
    with patch(f"{SEND}.convert_to_ogg", return_value=str(ogg)):
        assert await send(bot, path, limit=50) is False
    bot.send_audio.assert_not_called()


def test_flood_wait_secs():
    assert flood_wait_secs(RetryAfter(4)) == 4.5
    assert flood_wait_secs(BadRequest("retry after 12")) == 12.5
    assert flood_wait_secs(BadRequest("file is too big")) is None
