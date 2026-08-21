"""safe_edit swallows transient Telegram errors."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from music_downloader.telegram.ui.editing import safe_edit as _safe_edit


class TestSafeEdit:
    @pytest.mark.asyncio
    async def test_success(self):
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        result = await _safe_edit(msg, "new text")
        assert result is True
        msg.edit_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_bad_request(self):
        from telegram.error import BadRequest

        msg = AsyncMock()
        msg.edit_text = AsyncMock(side_effect=BadRequest("Message not modified"))
        result = await _safe_edit(msg, "text")
        assert result is False

    @pytest.mark.asyncio
    async def test_timed_out(self):
        from telegram.error import TimedOut

        msg = AsyncMock()
        msg.edit_text = AsyncMock(side_effect=TimedOut())
        result = await _safe_edit(msg, "text")
        assert result is False

    @pytest.mark.asyncio
    async def test_network_error(self):
        from telegram.error import NetworkError

        msg = AsyncMock()
        msg.edit_text = AsyncMock(side_effect=NetworkError("connection failed"))
        result = await _safe_edit(msg, "text")
        assert result is False
