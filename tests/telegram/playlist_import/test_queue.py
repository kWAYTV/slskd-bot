"""Job queue advancement."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from music_downloader.playlist_import import JobStatus
from tests.telegram.playlist_import.helpers import (
    _fake_to_thread,
    _make_context,
    _make_import_track,
    _setup_bot,
)


class TestProcessNextImportTrack:
    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    async def test_process_next_no_more_tracks(self, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        bot._active_import[chat_id] = 1
        bot.import_repo.get_next_pending_track = MagicMock(return_value=None)
        bot.import_repo.get_job_progress = MagicMock(return_value=(7, 2, 1, 10))
        bot.import_repo.update_job_status = MagicMock()
        context = _make_context()
        await bot._process_next_import_track(context, chat_id, 1, generation=0)
        bot.import_repo.update_job_status.assert_called_once_with(1, JobStatus.completed)
        assert chat_id not in bot._active_import
        context.bot.send_message.assert_awaited_once()
        msg_text = context.bot.send_message.call_args[1]["text"]
        assert "Import complete" in msg_text
        assert "7" in msg_text  # completed
        assert "2" in msg_text  # failed

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch("music_downloader.telegram.playlist_import.search.safe_edit", new_callable=AsyncMock, return_value=True)
    async def test_process_next_has_track(self, mock_edit, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        next_track = _make_import_track(track_id=3, job_id=1, position=4)
        bot.import_repo.get_next_pending_track = MagicMock(return_value=next_track)
        bot.import_repo.get_job_progress = MagicMock(return_value=(3, 0, 0, 10))
        bot.import_repo.update_track_status = MagicMock()
        bot.slskd.search = AsyncMock(return_value=[])
        context = _make_context()
        await bot._process_next_import_track(context, chat_id, 1, generation=0)
        bot.import_repo.update_track_status.assert_called()
        context.bot.send_message.assert_awaited()


# ---------------------------------------------------------------------------
# _do_import_slskd_search
# ---------------------------------------------------------------------------
