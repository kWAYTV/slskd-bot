"""Direct (metadata-free) Soulseek search."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from slskd_importer.telegram.core.session import PendingSearch
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

    async def test_direct_search_starts_immediately(self):
        bot = _setup_bot()
        chat_id = 67890
        bot.pending[chat_id] = PendingSearch(query="nancy sinatra - bang bang", track=_make_track())
        bot._do_direct_slskd_search = AsyncMock()
        update = _make_update(chat_id=chat_id)
        update.callback_query.message = MagicMock(message_id=7)
        context = _make_context()
        await bot._handle_direct_search(update, context, chat_id, "direct:search")
        update.callback_query.edit_message_text.assert_awaited_once()
        msg = update.callback_query.edit_message_text.call_args[0][0]
        assert "Saving as" in msg
        bot._do_direct_slskd_search.assert_awaited_once()
        assert bot._do_direct_slskd_search.await_args.args[2] == "nancy sinatra - bang bang"
        display_track = bot._do_direct_slskd_search.await_args.kwargs["display_track"]
        assert display_track.artist == "Nancy Sinatra"
        assert display_track.title == "Bang Bang"


# ---------------------------------------------------------------------------
# _do_direct_slskd_search
# ---------------------------------------------------------------------------


class TestDoDirectSlskdSearch:
    @patch("slskd_importer.telegram.search.direct.rank_responses", return_value=([], False))
    @patch("slskd_importer.telegram.search.direct.safe_edit", new_callable=AsyncMock, return_value=True)
    async def test_direct_search_no_results(self, mock_edit, mock_rank):
        bot = _setup_bot()
        chat_id = 67890
        bot.slskd.search = AsyncMock(return_value=[])
        searching_msg = MagicMock(message_id=100)
        await bot._do_direct_slskd_search(_make_context(), chat_id, "test query", searching_msg, generation=0)
        mock_edit.assert_awaited()
        assert "No results" in mock_edit.call_args[0][1]

    @patch("slskd_importer.telegram.search.direct.rank_responses")
    @patch("slskd_importer.telegram.search.direct.safe_edit", new_callable=AsyncMock, return_value=True)
    async def test_direct_search_finds_results(self, mock_edit, mock_rank):
        bot = _setup_bot()
        chat_id = 67890
        results = [_make_result(0), _make_result(1)]
        bot.slskd.search = AsyncMock(return_value=[{"username": "u", "files": []}])
        mock_rank.return_value = (results, False)
        searching_msg = MagicMock(message_id=100)
        await bot._do_direct_slskd_search(_make_context(), chat_id, "test query", searching_msg, generation=0)
        assert chat_id in bot.pending
        assert bot.pending[chat_id].results == results
        mock_edit.assert_awaited()
