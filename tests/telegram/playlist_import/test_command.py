"""/import command: resolve, confirm, guard rails."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from slskd_importer.catalog.playlist import PlaylistInfo
from tests.telegram.playlist_import.helpers import (
    _fake_to_thread,
    _make_context,
    _make_import_job,
    _make_track,
    _make_update,
    _setup_bot,
)


class TestCmdImport:
    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch("slskd_importer.telegram.playlist_import.command.safe_edit", new_callable=AsyncMock, return_value=True)
    async def test_cmd_import_no_args(self, mock_edit, mock_thread):
        bot = _setup_bot()
        update = _make_update(text="/import")
        context = _make_context()
        await bot.cmd_import(update, context)
        update.message.reply_text.assert_awaited_once()
        assert "/import" in update.message.reply_text.call_args[0][0]

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch("slskd_importer.telegram.playlist_import.command.safe_edit", new_callable=AsyncMock, return_value=True)
    async def test_cmd_import_invalid_url(self, mock_edit, mock_thread):
        bot = _setup_bot()
        update = _make_update(text="/import https://example.com/not-spotify")
        context = _make_context()
        await bot.cmd_import(update, context)
        update.message.reply_text.assert_awaited_once()
        assert "Spotify playlist or album URL" in update.message.reply_text.call_args[0][0]

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch("slskd_importer.telegram.playlist_import.command.safe_edit", new_callable=AsyncMock, return_value=True)
    @patch("slskd_importer.telegram.playlist_import.command.PlaylistResolver.is_spotify_url", return_value=True)
    async def test_cmd_import_active_job_exists(self, mock_is_url, mock_edit, mock_thread):
        bot = _setup_bot()
        bot.import_repo.get_active_job = MagicMock(return_value=_make_import_job())
        update = _make_update(text="/import https://open.spotify.com/playlist/abc123")
        context = _make_context()
        context.application.create_task = lambda coro, **kw: asyncio.ensure_future(coro)
        await bot.cmd_import(update, context)
        await asyncio.sleep(0)
        update.message.reply_text.assert_awaited_once()
        assert "already running" in update.message.reply_text.call_args[0][0]

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch("slskd_importer.telegram.playlist_import.command.safe_edit", new_callable=AsyncMock, return_value=True)
    @patch("slskd_importer.telegram.playlist_import.command.PlaylistResolver.is_spotify_url", return_value=True)
    async def test_cmd_import_resolve_fails(self, mock_is_url, mock_edit, mock_thread):
        bot = _setup_bot()
        bot.import_repo.get_active_job = MagicMock(return_value=None)
        bot.playlist_resolver.resolve = MagicMock(return_value=None)
        update = _make_update(text="/import https://open.spotify.com/playlist/abc123")
        context = _make_context()
        context.application.create_task = lambda coro, **kw: asyncio.ensure_future(coro)
        await bot.cmd_import(update, context)
        await asyncio.sleep(0)
        mock_edit.assert_awaited()
        assert "could not be resolved" in mock_edit.call_args[0][1]

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    @patch("slskd_importer.telegram.playlist_import.command.safe_edit", new_callable=AsyncMock, return_value=True)
    @patch("slskd_importer.telegram.playlist_import.command.PlaylistResolver.is_spotify_url", return_value=True)
    @patch("slskd_importer.telegram.playlist_import.command.build_import_confirm_keyboard", return_value=None)
    async def test_cmd_import_success(self, mock_kb, mock_is_url, mock_edit, mock_thread):
        bot = _setup_bot()
        bot.import_repo.get_active_job = MagicMock(return_value=None)
        bot.import_repo.create_job = MagicMock(return_value=42)
        bot.import_repo.add_tracks = MagicMock()
        playlist_info = PlaylistInfo(
            name="My Playlist",
            owner="TestUser",
            total_tracks=3,
            spotify_url="https://open.spotify.com/playlist/abc123",
            tracks=[_make_track(), _make_track(), _make_track()],
            is_album=False,
        )
        bot.playlist_resolver.resolve = MagicMock(return_value=playlist_info)
        update = _make_update(text="/import https://open.spotify.com/playlist/abc123")
        context = _make_context()
        context.application.create_task = lambda coro, **kw: asyncio.ensure_future(coro)
        await bot.cmd_import(update, context)
        await asyncio.sleep(0)
        bot.import_repo.create_job.assert_called_once()
        bot.import_repo.add_tracks.assert_called_once()
        call_args = bot.import_repo.add_tracks.call_args[0]
        assert call_args[0] == 42
        assert len(call_args[1]) == 3
        mock_edit.assert_awaited()
        assert "My Playlist" in mock_edit.call_args[0][1]

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    async def test_cmd_import_resume(self, mock_thread):
        bot = _setup_bot()
        job = _make_import_job()
        bot.import_repo.get_active_job = MagicMock(return_value=job)
        bot.import_repo.reset_in_flight_tracks = MagicMock(return_value=2)
        bot.import_repo.update_job_status = MagicMock()
        bot._process_next_import_track = AsyncMock()
        update = _make_update(text="/import resume")
        context = _make_context()

        def _create_task(coro, **kw):
            if hasattr(coro, "close"):
                coro.close()
            return MagicMock()

        context.application.create_task = _create_task
        await bot.cmd_import(update, context)
        bot.import_repo.reset_in_flight_tracks.assert_called_once_with(job.id)
        assert bot._active_import[67890] == job.id
        context.bot.send_message.assert_awaited()
        assert "Resuming" in context.bot.send_message.call_args.kwargs["text"]

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    async def test_cmd_import_resume_nothing(self, mock_thread):
        bot = _setup_bot()
        update = _make_update(text="/import resume")
        context = _make_context()
        await bot.cmd_import(update, context)
        context.bot.send_message.assert_awaited_once()
        assert "Nothing to resume" in context.bot.send_message.call_args.kwargs["text"]

    @patch("asyncio.to_thread", side_effect=_fake_to_thread)
    async def test_cmd_import_no_args_with_active_job(self, mock_thread):
        bot = _setup_bot()
        job = _make_import_job()
        bot.import_repo.get_active_job = MagicMock(return_value=job)
        bot.import_repo.reset_in_flight_tracks = MagicMock(return_value=2)
        bot.import_repo.update_job_status = MagicMock()
        bot._process_next_import_track = AsyncMock()
        update = _make_update(text="/import")
        context = _make_context()

        def _create_task(coro, **kw):
            if hasattr(coro, "close"):
                coro.close()
            return MagicMock()

        context.application.create_task = _create_task
        await bot.cmd_import(update, context)
        bot.import_repo.reset_in_flight_tracks.assert_called_once_with(job.id)
        context.bot.send_message.assert_awaited()
        assert "Resuming" in context.bot.send_message.call_args.kwargs["text"]
