"""Approval flow: dismissal, caption edits, cross-chat protection."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from slskd_importer.telegram.core.app import MusicBot
from slskd_importer.telegram.core.session import PendingDownload, PendingSearch
from tests.telegram.helpers import (
    _make_callback_update,
    _make_config,
    _make_context,
    _make_search_result,
    _make_track,
)


class TestMusicBotDismissOtherDownloads:
    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_dismiss(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.pending[67890] = PendingSearch(query="test", track=_make_track(), message_id=100)
        bot.downloads["2"] = PendingDownload(
            track=_make_track(),
            result=_make_search_result(),
            chat_id=67890,
            approval_message_id=200,
        )
        context = _make_context()
        await bot._dismiss_other_downloads(context, 67890)
        assert 67890 not in bot.pending
        assert "2" not in bot.downloads


class TestMusicBotEditApprovalMessage:
    @pytest.mark.asyncio
    async def test_edit_caption(self):
        query = AsyncMock()
        query.edit_message_caption = AsyncMock()
        await MusicBot._edit_approval_message(query, "test")
        query.edit_message_caption.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_to_text(self):
        query = AsyncMock()
        query.edit_message_caption = AsyncMock(side_effect=Exception("no caption"))
        query.edit_message_text = AsyncMock()
        await MusicBot._edit_approval_message(query, "test")
        query.edit_message_text.assert_called_once()


# ---------------------------------------------------------------------------
# IDOR protection tests
# ---------------------------------------------------------------------------


class TestIDORProtection:
    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_approval_idor_blocked(self, mock_slskd, mock_spotify):
        """Approval from a different chat_id should be silently rejected."""
        bot = MusicBot(_make_config())
        track = _make_track()
        result = _make_search_result()
        bot.downloads["1"] = PendingDownload(track=track, result=result, chat_id=111, source_path="/tmp/f.flac")
        update = _make_callback_update(chat_id=999, data="approve:1")
        context = _make_context()
        await bot.handle_callback(update, context)
        # Download should still be in the dict (not popped by wrong chat)
        assert "1" in bot.downloads

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_retry_idor_blocked(self, mock_slskd, mock_spotify):
        """Retry from a different chat_id should be silently rejected."""
        bot = MusicBot(_make_config())
        track = _make_track()
        result = _make_search_result()
        bot.downloads["1"] = PendingDownload(track=track, result=result, chat_id=111)
        update = _make_callback_update(chat_id=999, data="retry:1")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert "1" in bot.downloads

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_next_result_idor_blocked(self, mock_slskd, mock_spotify):
        """Next-result from a different chat should be silently rejected."""
        bot = MusicBot(_make_config())
        track = _make_track()
        result = _make_search_result()
        bot.downloads["1"] = PendingDownload(track=track, result=result, chat_id=111, result_index=0)
        bot.pending[999] = PendingSearch(query="test", track=track, results=[result, _make_search_result(1)])
        update = _make_callback_update(chat_id=999, data="next:1")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert "1" in bot.downloads


# ---------------------------------------------------------------------------
# Retry result_index tests
# ---------------------------------------------------------------------------
