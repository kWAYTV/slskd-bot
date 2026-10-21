"""Transfer pipeline: locate retry and giving up on slskd."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from slskd_importer.soulseek.result import DownloadStatus
from slskd_importer.telegram.core.app import MusicBot
from slskd_importer.telegram.download.transfer import fetch_from_peer, locate_landed
from tests.telegram.download.helpers import _make_config, _make_result


@pytest.mark.asyncio
async def test_locate_landed_retries_then_finds():
    looks = {"n": 0}

    def find():
        looks["n"] += 1
        return "/tmp/song.flac" if looks["n"] >= 3 else None

    slept: list[float] = []

    async def fake_sleep(secs):
        slept.append(secs)

    path = await locate_landed(find, sleep=fake_sleep)
    assert path == "/tmp/song.flac"
    assert looks["n"] == 3
    assert slept == [0.5, 0.5]


@pytest.mark.asyncio
async def test_locate_landed_gives_up_after_budget():
    async def fake_sleep(_secs):
        return None

    with (
        patch("slskd_importer.telegram.download.transfer.LOCATE_RETRY_SECS", 1.0),
        patch("slskd_importer.telegram.download.transfer.LOCATE_RETRY_STEP_SECS", 0.5),
    ):
        path = await locate_landed(lambda: None, sleep=fake_sleep)
    assert path is None


@patch("slskd_importer.telegram.core.app.SpotifyResolver")
@patch("slskd_importer.telegram.core.app.SlskdClient")
@pytest.mark.asyncio
async def test_fetch_cancels_slskd_on_timeout(mock_slskd_cls, mock_spotify):
    bot = MusicBot(_make_config())
    bot.slskd = MagicMock()
    bot.slskd.enqueue_download = MagicMock(return_value=True)
    bot.slskd.wait_for_download = AsyncMock(return_value=None)
    bot.slskd.cancel_transfer = MagicMock(return_value=True)

    outcome = await fetch_from_peer(bot, _make_result(), AsyncMock())
    assert outcome.enqueued is True
    assert outcome.failed is True
    bot.slskd.cancel_transfer.assert_called_once()


@patch("slskd_importer.telegram.core.app.SpotifyResolver")
@patch("slskd_importer.telegram.core.app.SlskdClient")
@pytest.mark.asyncio
async def test_fetch_cancels_slskd_on_failed_status(mock_slskd_cls, mock_spotify):
    bot = MusicBot(_make_config())
    bot.slskd = MagicMock()
    bot.slskd.enqueue_download = MagicMock(return_value=True)
    bot.slskd.wait_for_download = AsyncMock(
        return_value=DownloadStatus(username="u", filename="f", state="Errored", transfer_id="xfer-1")
    )
    bot.slskd.cancel_transfer = MagicMock(return_value=True)

    outcome = await fetch_from_peer(bot, _make_result(), AsyncMock())
    assert outcome.failed is True
    bot.slskd.cancel_transfer.assert_called_once()
    assert bot.slskd.cancel_transfer.call_args[0][2] == "xfer-1"
