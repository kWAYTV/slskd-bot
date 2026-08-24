"""/cancel command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from slskd_importer.playlist_import import JobStatus
from tests.telegram.playlist_import.helpers import (
    _fake_to_thread,
    _make_context,
    _make_update,
    _setup_bot,
)


class TestCmdCancel:
    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    async def test_cmd_cancel_active_import(self, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        bot._active_import[chat_id] = 42
        bot.import_repo.update_job_status = MagicMock()
        update = _make_update(chat_id=chat_id, text="/cancel")
        context = _make_context()
        await bot.cmd_cancel(update, context)
        bot.import_repo.update_job_status.assert_called_once_with(42, JobStatus.cancelled)
        update.message.reply_text.assert_awaited_once()
        assert "Import cancelled" in update.message.reply_text.call_args[0][0]

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    async def test_cmd_cancel_no_work(self, mock_thread):
        bot = _setup_bot()
        update = _make_update(chat_id=67890, text="/cancel")
        context = _make_context()
        await bot.cmd_cancel(update, context)
        update.message.reply_text.assert_awaited_once()
        assert "Nothing to cancel" in update.message.reply_text.call_args[0][0]


# ---------------------------------------------------------------------------
# _handle_import_callback
# ---------------------------------------------------------------------------
