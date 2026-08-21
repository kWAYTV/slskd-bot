"""Import track download and delivery."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from music_downloader.playlist_import import TrackStatus
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


class TestDoImportDownload:
    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch("music_downloader.telegram.playlist_import.download.safe_edit", new_callable=AsyncMock, return_value=True)
    async def test_import_download_enqueue_fails(self, mock_edit, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        bot.slskd.enqueue_download = MagicMock(return_value=False)
        bot.import_repo.update_track_status = MagicMock()
        result = _make_result()
        status_msg = MagicMock(message_id=100)
        dl_id = "dl_1"
        bot.downloads[dl_id] = PendingDownload(track=_make_track(), result=result, chat_id=chat_id)
        context = _make_context()
        await bot._do_import_download(
            context,
            chat_id,
            _make_track(),
            result,
            status_msg,
            generation=0,
            job_id=1,
            track_id=5,
            dl_id=dl_id,
        )
        mock_edit.assert_awaited()
        assert "Failed to enqueue" in mock_edit.call_args[0][1]
        bot.import_repo.update_track_status.assert_called_with(5, TrackStatus.awaiting_approval)

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch("music_downloader.telegram.playlist_import.download.safe_edit", new_callable=AsyncMock, return_value=True)
    async def test_import_download_timeout(self, mock_edit, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        bot.slskd.enqueue_download = MagicMock(return_value=True)
        bot.slskd.wait_for_download = AsyncMock(return_value=None)
        bot.import_repo.update_track_status = MagicMock()
        result = _make_result()
        status_msg = MagicMock(message_id=100)
        dl_id = "dl_2"
        bot.downloads[dl_id] = PendingDownload(track=_make_track(), result=result, chat_id=chat_id)
        context = _make_context()
        await bot._do_import_download(
            context,
            chat_id,
            _make_track(),
            result,
            status_msg,
            generation=0,
            job_id=1,
            track_id=5,
            dl_id=dl_id,
        )
        mock_edit.assert_awaited()
        assert "Download failed" in mock_edit.call_args[0][1]
        markup = mock_edit.call_args.kwargs.get("reply_markup") or mock_edit.call_args[1].get("reply_markup")
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert "iy:1:5:dl_2" in callbacks
        assert "is:1:5" in callbacks
        assert "ir:1:5" in callbacks
        bot.import_repo.update_track_status.assert_called_with(5, TrackStatus.awaiting_approval)

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch(
        "music_downloader.telegram.playlist_import.callbacks.safe_query_edit", new_callable=AsyncMock, return_value=True
    )
    async def test_import_retry_uses_import_flow(self, mock_qedit, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        job = _make_import_job(job_id=1, chat_id=chat_id)
        bot.import_repo.get_job_for_chat = MagicMock(return_value=job)
        bot.import_repo.update_track_status = MagicMock()
        result = _make_result()
        bot.downloads["dl_7"] = PendingDownload(track=_make_track(), result=result, chat_id=chat_id)
        update = _make_update(chat_id=chat_id)
        context = _make_context()

        def _create_task(coro, **kw):
            coro.close()
            return MagicMock()

        context.application.create_task = MagicMock(side_effect=_create_task)
        await bot._handle_import_callback(update, context, chat_id, "iy:1:5:dl_7")
        bot.import_repo.update_track_status.assert_called_with(5, TrackStatus.searching)
        context.application.create_task.assert_called_once()
        # Download stays registered so _do_import_download can attach source_path
        assert "dl_7" in bot.downloads

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch(
        "music_downloader.telegram.playlist_import.callbacks.safe_query_edit", new_callable=AsyncMock, return_value=True
    )
    async def test_import_retry_expired_download(self, mock_qedit, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        job = _make_import_job(job_id=1, chat_id=chat_id)
        bot.import_repo.get_job_for_chat = MagicMock(return_value=job)
        update = _make_update(chat_id=chat_id)
        context = _make_context()
        await bot._handle_import_callback(update, context, chat_id, "iy:1:5:missing")
        context.application.create_task.assert_not_called()
        assert "expired" in mock_qedit.call_args[0][1]

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    async def test_import_approve_denied_for_non_library_user(self, mock_thread):
        bot = _setup_bot()
        bot.config.telegram_library_users = {12345}
        chat_id = 67890
        bot.downloads["dl_9"] = PendingDownload(track=_make_track(), result=_make_result(), chat_id=chat_id)
        bot._edit_approval_message = AsyncMock()
        update = _make_update(chat_id=chat_id)
        update.callback_query.from_user.id = 55555  # allowed but not a library user
        context = _make_context()
        await bot._handle_import_approve(update, context, chat_id, 1, 5, "dl_9")
        assert "dl_9" in bot.downloads  # not consumed
        assert "not allowed" in bot._edit_approval_message.call_args[0][1]

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch("music_downloader.telegram.playlist_import.download.safe_edit", new_callable=AsyncMock, return_value=True)
    async def test_import_download_success_large_file(self, mock_edit, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        bot.slskd.enqueue_download = MagicMock(return_value=True)
        status = MagicMock()
        status.is_failed = False
        bot.slskd.wait_for_download = AsyncMock(return_value=status)
        # Create a file larger than TELEGRAM_FILE_LIMIT
        with tempfile.NamedTemporaryFile(delete=False, suffix=".flac") as source:
            source.write(b"x" * 100)
        bot.processor = MagicMock()
        bot.processor.find_downloaded_file = MagicMock(return_value=source.name)
        bot.import_repo.update_track_status = MagicMock()
        result = _make_result()
        status_msg = MagicMock(message_id=100)
        dl_id = "dl_3"
        bot.downloads[dl_id] = PendingDownload(track=_make_track(), result=result, chat_id=chat_id)
        context = _make_context()
        # Set the file limit smaller than our file
        bot.config.telegram_file_limit = 50
        await bot._do_import_download(
            context,
            chat_id,
            _make_track(),
            result,
            status_msg,
            generation=0,
            job_id=1,
            track_id=5,
            dl_id=dl_id,
        )
        mock_edit.assert_awaited()
        assert "too large" in mock_edit.call_args[0][1]
        os.unlink(source.name)

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch("music_downloader.telegram.playlist_import.download.safe_edit", new_callable=AsyncMock, return_value=True)
    async def test_import_download_success_sends_audio(self, mock_edit, mock_thread):
        bot = _setup_bot()
        chat_id = 67890
        bot.slskd.enqueue_download = MagicMock(return_value=True)
        status = MagicMock()
        status.is_failed = False
        bot.slskd.wait_for_download = AsyncMock(return_value=status)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".flac") as source:
            source.write(b"fake audio")
        bot.processor = MagicMock()
        bot.processor.find_downloaded_file = MagicMock(return_value=source.name)
        bot.processor.build_filename = MagicMock(return_value="Artist - Title.flac")
        bot.import_repo.update_track_status = MagicMock()
        result = _make_result()
        status_msg = MagicMock(message_id=100)
        dl_id = "dl_4"
        bot.downloads[dl_id] = PendingDownload(track=_make_track(), result=result, chat_id=chat_id)
        context = _make_context()
        await bot._do_import_download(
            context,
            chat_id,
            _make_track(),
            result,
            status_msg,
            generation=0,
            job_id=1,
            track_id=5,
            dl_id=dl_id,
        )
        context.bot.send_audio.assert_awaited_once()
        bot.import_repo.update_track_status.assert_called_with(5, TrackStatus.awaiting_approval)
        os.unlink(source.name)


# ---------------------------------------------------------------------------
# _handle_direct_search
# ---------------------------------------------------------------------------
