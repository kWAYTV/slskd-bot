"""Import job resume after restart."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from tests.telegram.playlist_import.helpers import (
    _fake_to_thread,
    _make_import_job,
    _setup_bot,
)


class TestResumeStaleImports:
    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    async def test_skips_pending_confirmation_jobs(self, mock_thread):
        bot = _setup_bot()
        pending = _make_import_job(status="pending")
        bot.import_repo.list_resumable_jobs = MagicMock(return_value=[pending])
        application = MagicMock()
        application.bot = AsyncMock()
        application.create_task = MagicMock()
        await bot.resume_stale_imports(application)
        application.create_task.assert_not_called()
        assert pending.chat_id not in bot._active_import

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    async def test_resumes_active_jobs(self, mock_thread):
        bot = _setup_bot()
        job = _make_import_job(status="active")
        bot.import_repo.list_resumable_jobs = MagicMock(return_value=[job])
        bot.import_repo.reset_in_flight_tracks = MagicMock(return_value=1)
        bot._process_next_import_track = AsyncMock()
        application = MagicMock()
        application.bot = AsyncMock()

        def _create_task(coro, **kw):
            if hasattr(coro, "close"):
                coro.close()
            return MagicMock()

        with patch(
            "slskd_importer.telegram.playlist_import.resume.asyncio.create_task",
            side_effect=_create_task,
        ):
            await bot.resume_stale_imports(application)
        assert bot._active_import[job.chat_id] == job.id
        application.bot.send_message.assert_awaited()


# ---------------------------------------------------------------------------
# cmd_cancel
# ---------------------------------------------------------------------------
