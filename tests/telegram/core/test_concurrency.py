"""Concurrent searches must not cancel in-flight downloads."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from slskd_importer.telegram.core.app import MusicBot
from slskd_importer.telegram.core.session import PendingDownload, PendingSearch
from tests.telegram.helpers import (
    _make_config,
    _make_context,
    _make_search_result,
    _make_track,
    _make_update,
)


class TestConcurrentSearches:
    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_new_search_does_not_cancel_download(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._do_search = AsyncMock()
        bot.downloads["1"] = PendingDownload(
            track=_make_track(),
            result=_make_search_result(),
            chat_id=67890,
            search_id="old",
        )
        bot.pending["old"] = PendingSearch(
            query="first", track=_make_track(), chat_id=67890, search_id="old", results=[_make_search_result()]
        )
        await bot.handle_text(_make_update(text="second song"), _make_context())
        await asyncio.sleep(0)
        assert "1" in bot.downloads
        assert "old" in bot.pending
        bot._do_search.assert_awaited_once()
        assert bot._do_search.await_args.args[2] == "second song"

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_approve_does_not_dismiss_other_search(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.processor.process_file = lambda *a, **k: "/music/A - T.flac"
        bot._embed_spotify_artwork = AsyncMock()
        bot.downloads["keep"] = PendingDownload(
            track=_make_track(),
            result=_make_search_result(),
            chat_id=67890,
            search_id="2",
            source_path="/downloads/b.flac",
        )
        bot.downloads["done"] = PendingDownload(
            track=_make_track(),
            result=_make_search_result(),
            chat_id=67890,
            search_id="1",
            source_path="/downloads/a.flac",
        )
        from tests.telegram.helpers import _make_callback_update

        update = _make_callback_update(data="approve:done")
        await bot.handle_callback(update, _make_context())
        assert "keep" in bot.downloads
        assert "done" not in bot.downloads
