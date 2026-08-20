"""Free-text message handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from music_downloader.telegram.core.app import MusicBot
from tests.telegram.helpers import (
    _make_config,
    _make_context,
    _make_update,
)


class TestMusicBotHandleText:
    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_empty_text_ignored(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_update(text="   ")
        context = _make_context()
        await bot.handle_text(update, context)
        # Should not proceed to search

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_similar_files_found(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.processor = MagicMock()
        bot.processor.find_similar = MagicMock(return_value=["Artist - Song.flac"])
        update = _make_update(text="Artist Song")
        context = _make_context()
        await bot.handle_text(update, context)
        # Should show duplicate warning
        update.message.reply_text.assert_called_once()
        call_text = update.message.reply_text.call_args[0][0]
        assert "Similar files" in call_text

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_unauthorized_text(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.telegram_allowed_users = {11111}
        bot = MusicBot(config)
        update = _make_update(user_id=99999, text="test")
        context = _make_context()
        await bot.handle_text(update, context)
        update.message.reply_text.assert_called_once_with("You are not authorized to use this bot.")
