"""Retry and next-result selection."""

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


class TestRetryResultIndex:
    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_retry_preserves_result_index(self, mock_slskd, mock_spotify):
        """Retry should pass the stored result_index, not hardcoded 0."""
        bot = MusicBot(_make_config())
        track = _make_track()
        result = _make_search_result(3)
        bot.downloads["5"] = PendingDownload(track=track, result=result, chat_id=67890, result_index=3)
        update = _make_callback_update(chat_id=67890, data="retry:5")
        context = _make_context()

        with patch.object(bot, "_do_download", new_callable=AsyncMock) as mock_dl:
            await bot.handle_callback(update, context)
            mock_dl.assert_called_once()
            # result_index is the last positional arg
            assert mock_dl.call_args[0][-1] == 3

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_retry_pops_old_entry(self, mock_slskd, mock_spotify):
        """Retry should remove the old download entry to prevent leaks."""
        bot = MusicBot(_make_config())
        track = _make_track()
        result = _make_search_result()
        bot.downloads["1"] = PendingDownload(track=track, result=result, chat_id=67890)
        update = _make_callback_update(chat_id=67890, data="retry:1")
        context = _make_context()

        with patch.object(bot, "_do_download", new_callable=AsyncMock):
            await bot.handle_callback(update, context)
            assert "1" not in bot.downloads

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_next_result_uses_stored_index(self, mock_slskd, mock_spotify):
        """Next-result should use stored result_index + 1."""
        bot = MusicBot(_make_config())
        track = _make_track()
        results = [_make_search_result(i) for i in range(5)]
        bot.pending["1"] = PendingSearch(query="test", track=track, results=results, chat_id=67890, search_id="1")
        bot.downloads["2"] = PendingDownload(
            track=track, result=results[2], chat_id=67890, result_index=2, search_id="1"
        )
        update = _make_callback_update(chat_id=67890, data="next:2")
        context = _make_context()

        with patch.object(bot, "_do_download", new_callable=AsyncMock) as mock_dl:
            await bot.handle_callback(update, context)
            mock_dl.assert_called_once()
            # Should download results[3] with index=3
            call_args = mock_dl.call_args[0]
            assert call_args[3] == results[3]  # next_result
            assert call_args[-1] == 3  # next_idx

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_next_result_exhausted(self, mock_slskd, mock_spotify):
        """Next-result on last result should show 'no more results'."""
        bot = MusicBot(_make_config())
        track = _make_track()
        results = [_make_search_result(0)]
        bot.pending["1"] = PendingSearch(query="test", track=track, results=results, chat_id=67890, search_id="1")
        bot.downloads["1"] = PendingDownload(
            track=track, result=results[0], chat_id=67890, result_index=0, search_id="1"
        )
        update = _make_callback_update(chat_id=67890, data="next:1")
        context = _make_context()
        await bot.handle_callback(update, context)
        edit_call = update.callback_query.edit_message_text
        assert "No more results" in edit_call.call_args[0][0]


# ---------------------------------------------------------------------------
# _rank_responses tests
# ---------------------------------------------------------------------------
