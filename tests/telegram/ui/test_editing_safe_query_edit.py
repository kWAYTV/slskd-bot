"""safe_query_edit swallows transient Telegram errors."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from telegram.error import BadRequest, NetworkError, TimedOut

from music_downloader.telegram.ui.editing import safe_query_edit as _safe_query_edit


class TestSafeQueryEdit:
    async def test_safe_query_edit_success(self):
        query = MagicMock()
        query.edit_message_text = AsyncMock()
        result = await _safe_query_edit(query, "hello")
        assert result is True
        query.edit_message_text.assert_awaited_once_with("hello")

    async def test_safe_query_edit_bad_request(self):
        query = MagicMock()
        query.edit_message_text = AsyncMock(side_effect=BadRequest("message not modified"))
        result = await _safe_query_edit(query, "hello")
        assert result is False

    async def test_safe_query_edit_timed_out(self):
        query = MagicMock()
        query.edit_message_text = AsyncMock(side_effect=TimedOut())
        result = await _safe_query_edit(query, "hello")
        assert result is False

    async def test_safe_query_edit_network_error(self):
        query = MagicMock()
        query.edit_message_text = AsyncMock(side_effect=NetworkError("connection reset"))
        result = await _safe_query_edit(query, "hello")
        assert result is False


# ---------------------------------------------------------------------------
# cmd_import
# ---------------------------------------------------------------------------
