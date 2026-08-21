"""Direct (metadata-free) Soulseek search."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from music_downloader.telegram.core.session import PendingSearch
from tests.telegram.playlist_import.helpers import (
    _make_context,
    _make_result,
    _make_track,
    _make_update,
    _setup_bot,
)


class TestHandleDirectSearch:
    async def test_direct_search_no_pending(self):
        bot = _setup_bot()
        chat_id = 67890
        update = _make_update(chat_id=chat_id)
        context = _make_context()
        await bot._handle_direct_search(update, context, chat_id, "direct_search")
        update.callback_query.edit_message_text.assert_awaited_once()
        assert "expired" in update.callback_query.edit_message_text.call_args[0][0]

    async def test_direct_search_prompts_for_metadata(self):
        bot = _setup_bot()
        chat_id = 67890
        bot.pending[chat_id] = PendingSearch(query="test query", track=_make_track())
        update = _make_update(chat_id=chat_id)
        context = _make_context()
        await bot._handle_direct_search(update, context, chat_id, "direct_search")
        update.callback_query.edit_message_text.assert_awaited_once()
        msg = update.callback_query.edit_message_text.call_args[0][0]
        assert "Artist - Title" in msg
        assert chat_id in bot._awaiting_direct_metadata
        assert bot._awaiting_direct_metadata[chat_id] == "test query"


# ---------------------------------------------------------------------------
# _do_direct_slskd_search
# ---------------------------------------------------------------------------


class TestDoDirectSlskdSearch:
    @patch("music_downloader.telegram.search.direct.safe_edit", new_callable=AsyncMock, return_value=True)
    async def test_direct_search_no_results(self, mock_edit):
        bot = _setup_bot()
        chat_id = 67890
        bot.slskd.search = AsyncMock(return_value=[])
        bot._rank_responses = MagicMock(return_value=([], False))
        searching_msg = MagicMock(message_id=100)
        await bot._do_direct_slskd_search(_make_context(), chat_id, "test query", searching_msg, generation=0)
        mock_edit.assert_awaited()
        assert "No results" in mock_edit.call_args[0][1]

    @patch("music_downloader.telegram.search.direct.safe_edit", new_callable=AsyncMock, return_value=True)
    async def test_direct_search_finds_results(self, mock_edit):
        bot = _setup_bot()
        chat_id = 67890
        results = [_make_result(0), _make_result(1)]
        bot.slskd.search = AsyncMock(return_value=[{"username": "u", "files": []}])
        bot._rank_responses = MagicMock(return_value=(results, False))
        bot._format_results = MagicMock(return_value="Results text")
        searching_msg = MagicMock(message_id=100)
        await bot._do_direct_slskd_search(_make_context(), chat_id, "test query", searching_msg, generation=0)
        assert chat_id in bot.pending
        assert bot.pending[chat_id].results == results
        mock_edit.assert_awaited()
