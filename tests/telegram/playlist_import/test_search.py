"""Per-track Soulseek search inside an import job."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from slskd_importer.playlist_import import TrackStatus
from tests.telegram.playlist_import.helpers import (
    _fake_to_thread,
    _make_context,
    _make_track,
    _setup_bot,
)


class TestDoImportSlskdSearch:
    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch("slskd_importer.telegram.playlist_import.search.safe_edit", new_callable=AsyncMock, return_value=True)
    async def test_import_search_no_results(self, mock_edit, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        bot.slskd.search = AsyncMock(return_value=[])
        bot.import_repo.update_track_status = MagicMock()
        track = _make_track()
        searching_msg = MagicMock(message_id=100)
        await bot._do_import_slskd_search(
            _make_context(), chat_id, track, searching_msg, generation=0, job_id=1, track_id=5
        )
        mock_edit.assert_awaited()
        assert "No matches" in mock_edit.call_args[0][1]
        bot.import_repo.update_track_status.assert_called_with(5, TrackStatus.awaiting_approval)
        assert bot.slskd.search.await_count >= 1

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch("slskd_importer.telegram.playlist_import.search.safe_edit", new_callable=AsyncMock, return_value=True)
    async def test_import_search_success(self, mock_edit, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        # Return results from first search call
        bot.slskd.search = AsyncMock(
            return_value=[
                {"username": "user0", "files": [{"filename": "\\Music\\track0.flac", "size": 30000000, "length": 162}]}
            ]
        )
        bot.slskd.enqueue_download = MagicMock(return_value=True)
        bot.slskd.wait_for_download = AsyncMock()
        track = _make_track()
        searching_msg = MagicMock(message_id=100)
        context = _make_context()
        await bot._do_import_slskd_search(context, chat_id, track, searching_msg, generation=0, job_id=1, track_id=5)
        # Should store in _import_pending and start download task
        assert chat_id in bot._import_pending
        context.application.create_task.assert_called_once()

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch("slskd_importer.telegram.playlist_import.search.safe_edit", new_callable=AsyncMock, return_value=True)
    async def test_import_search_exception(self, mock_edit, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        bot.slskd.search = AsyncMock(side_effect=RuntimeError("network failure"))
        bot.import_repo.complete_track = MagicMock()
        bot.import_repo.get_next_pending_track = MagicMock(return_value=None)
        bot.import_repo.get_job_progress = MagicMock(return_value=(5, 1, 0, 10))
        bot.import_repo.update_job_status = MagicMock()
        track = _make_track()
        searching_msg = MagicMock(message_id=100)
        context = _make_context()
        await bot._do_import_slskd_search(context, chat_id, track, searching_msg, generation=0, job_id=1, track_id=5)
        bot.import_repo.complete_track.assert_called_once_with(1, 5, TrackStatus.failed, "Search error")


# ---------------------------------------------------------------------------
# _do_import_download
# ---------------------------------------------------------------------------
