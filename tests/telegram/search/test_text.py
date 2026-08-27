"""Free-text message handling."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from slskd_importer.telegram.core.app import MusicBot
from tests.telegram.helpers import (
    _make_config,
    _make_context,
    _make_update,
)


class TestMusicBotHandleText:
    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_empty_text_ignored(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_update(text="   ")
        context = _make_context()
        await bot.handle_text(update, context)
        # Should not proceed to search

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_text_query_starts_search(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._do_search = AsyncMock()
        update = _make_update(text="Artist Song")
        context = _make_context()
        await bot.handle_text(update, context)
        await asyncio.sleep(0)
        bot._do_search.assert_awaited_once()
        assert bot._do_search.await_args.args[2] == "Artist Song"
        assert bot._do_search.await_args.args[3] in bot.pending

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_unauthorized_text(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.telegram_allowed_users = {11111}
        bot = MusicBot(config)
        update = _make_update(user_id=99999, text="test")
        context = _make_context()
        await bot.handle_text(update, context)
        update.message.reply_text.assert_called_once_with("You are not authorized to use this bot.")
