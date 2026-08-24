"""Import keyboard callbacks: start, cancel, approve, retry, skip."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from music_downloader.playlist_import import JobStatus, TrackStatus
from music_downloader.telegram.core.session import PendingDownload
from tests.telegram.playlist_import.helpers import (
    _fake_to_thread,
    _make_context,
    _make_import_job,
    _make_result,
    _make_track,
    _make_update,
    _setup_bot,
)


class TestHandleImportCallback:
    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch(
        "music_downloader.telegram.playlist_import.callbacks.safe_query_edit", new_callable=AsyncMock, return_value=True
    )
    async def test_import_confirm_start(self, mock_qedit, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        job = _make_import_job(job_id=1, chat_id=chat_id)
        bot.import_repo.get_job_for_chat = MagicMock(return_value=job)
        bot.import_repo.update_job_status = MagicMock()
        update = _make_update(chat_id=chat_id)
        context = _make_context()
        await bot._handle_import_callback(update, context, chat_id, "ic:1")
        bot.import_repo.update_job_status.assert_called_once_with(1, JobStatus.active)
        assert bot._active_import[chat_id] == 1
        context.application.create_task.assert_called_once()

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch(
        "music_downloader.telegram.playlist_import.callbacks.safe_query_edit", new_callable=AsyncMock, return_value=True
    )
    async def test_import_cancel(self, mock_qedit, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        job = _make_import_job(job_id=1, chat_id=chat_id)
        bot.import_repo.get_job_for_chat = MagicMock(return_value=job)
        bot.import_repo.update_job_status = MagicMock()
        bot._active_import[chat_id] = 1
        update = _make_update(chat_id=chat_id)
        context = _make_context()
        await bot._handle_import_callback(update, context, chat_id, "ix:1")
        bot.import_repo.update_job_status.assert_called_once_with(1, JobStatus.cancelled)
        assert chat_id not in bot._active_import
        mock_qedit.assert_awaited()
        assert "cancelled" in mock_qedit.call_args[0][1]

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch(
        "music_downloader.telegram.playlist_import.callbacks.safe_query_edit", new_callable=AsyncMock, return_value=True
    )
    async def test_import_reject_track(self, mock_qedit, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        job = _make_import_job(job_id=1, chat_id=chat_id)
        bot.import_repo.get_job_for_chat = MagicMock(return_value=job)
        bot.import_repo.complete_track = MagicMock()
        bot.import_repo.get_next_pending_track = MagicMock(return_value=None)
        bot.import_repo.get_job_progress = MagicMock(return_value=(5, 1, 0, 10))
        bot.import_repo.update_job_status = MagicMock()
        update = _make_update(chat_id=chat_id)
        context = _make_context()
        await bot._handle_import_callback(update, context, chat_id, "ir:1:5")
        bot.import_repo.complete_track.assert_called_once_with(1, 5, TrackStatus.failed, "Rejected by user")

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch(
        "music_downloader.telegram.playlist_import.callbacks.safe_query_edit", new_callable=AsyncMock, return_value=True
    )
    async def test_import_skip_track(self, mock_qedit, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        job = _make_import_job(job_id=1, chat_id=chat_id)
        bot.import_repo.get_job_for_chat = MagicMock(return_value=job)
        bot.import_repo.complete_track = MagicMock()
        bot.import_repo.get_next_pending_track = MagicMock(return_value=None)
        bot.import_repo.get_job_progress = MagicMock(return_value=(5, 1, 1, 10))
        bot.import_repo.update_job_status = MagicMock()
        update = _make_update(chat_id=chat_id)
        context = _make_context()
        await bot._handle_import_callback(update, context, chat_id, "is:1:5")
        bot.import_repo.complete_track.assert_called_once_with(1, 5, TrackStatus.skipped)

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch(
        "music_downloader.telegram.playlist_import.callbacks.safe_query_edit", new_callable=AsyncMock, return_value=True
    )
    async def test_import_callback_wrong_chat(self, mock_qedit, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        bot.import_repo.get_job_for_chat = MagicMock(return_value=None)
        update = _make_update(chat_id=chat_id)
        context = _make_context()
        await bot._handle_import_callback(update, context, chat_id, "ic:1")
        mock_qedit.assert_awaited_once()
        assert "not found" in mock_qedit.call_args[0][1]


# ---------------------------------------------------------------------------
# _handle_import_approve
# ---------------------------------------------------------------------------


class TestHandleImportApprove:
    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch(
        "music_downloader.telegram.playlist_import.callbacks.safe_query_edit", new_callable=AsyncMock, return_value=True
    )
    async def test_import_approve_expired_download(self, mock_qedit, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        update = _make_update(chat_id=chat_id)
        # No download in bot.downloads
        bot.import_repo.get_next_pending_track = MagicMock(return_value=None)
        bot.import_repo.get_job_progress = MagicMock(return_value=(10, 0, 0, 10))
        bot.import_repo.update_job_status = MagicMock()
        await bot._handle_import_approve(update, _make_context(), chat_id, 1, 5, "nonexistent")

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch(
        "music_downloader.telegram.playlist_import.callbacks.safe_query_edit", new_callable=AsyncMock, return_value=True
    )
    async def test_import_approve_source_not_ready(self, mock_qedit, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        track = _make_track()
        result = _make_result()
        dl_id = "dl_1"
        bot.downloads[dl_id] = PendingDownload(track=track, result=result, chat_id=chat_id, source_path=None)
        update = _make_update(chat_id=chat_id)
        await bot._handle_import_approve(update, _make_context(), chat_id, 1, 5, dl_id)
        # Download should be put back
        assert dl_id in bot.downloads

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    async def test_import_approve_success(self, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        track = _make_track()
        result = _make_result()
        dl_id = "dl_2"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".flac") as source:
            source.write(b"fake flac data")
        bot.downloads[dl_id] = PendingDownload(track=track, result=result, chat_id=chat_id, source_path=source.name)
        bot.processor = MagicMock()
        bot.processor.process_file = MagicMock(return_value="/tmp/output.flac")
        bot.import_repo.complete_track = MagicMock()
        bot.import_repo.get_next_pending_track = MagicMock(return_value=None)
        bot.import_repo.get_job_progress = MagicMock(return_value=(10, 0, 0, 10))
        bot.import_repo.update_job_status = MagicMock()
        bot._embed_spotify_artwork = AsyncMock()
        bot._add_history = AsyncMock()
        bot._edit_approval_message = AsyncMock()
        update = _make_update(chat_id=chat_id)
        context = _make_context()
        await bot._handle_import_approve(update, context, chat_id, 1, 5, dl_id)
        bot.processor.process_file.assert_called_once_with(source.name, "Artist", "Title", album="Album", year="2024")
        bot.import_repo.complete_track.assert_called_once_with(1, 5, TrackStatus.completed)
        os.unlink(source.name)


# ---------------------------------------------------------------------------
# _process_next_import_track
# ---------------------------------------------------------------------------
