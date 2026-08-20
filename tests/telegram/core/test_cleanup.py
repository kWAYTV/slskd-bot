"""Cancellation and download artifact cleanup."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest

from music_downloader.telegram.core.app import MusicBot
from music_downloader.telegram.core.session import PendingDownload, PendingSearch
from tests.telegram.helpers import (
    _make_config,
    _make_search_result,
    _make_track,
)


class TestMusicBotCancellation:
    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cancel_chat_operations_empty(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        had_work = await bot._cancel_chat_operations(12345)
        assert had_work is False

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cancel_chat_operations_with_pending(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.pending[12345] = PendingSearch(query="test")
        had_work = await bot._cancel_chat_operations(12345)
        assert had_work is True
        assert 12345 not in bot.pending

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cancel_removes_downloads_for_chat(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.downloads["1"] = PendingDownload(
            track=_make_track(),
            result=_make_search_result(),
            chat_id=12345,
        )
        bot.downloads["2"] = PendingDownload(
            track=_make_track(),
            result=_make_search_result(),
            chat_id=99999,
        )
        await bot._cancel_chat_operations(12345)
        assert "1" not in bot.downloads
        assert "2" in bot.downloads

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_is_stale(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._chat_generation[123] = 5
        assert bot._is_stale(123, 5) is False
        assert bot._is_stale(123, 4) is True
        assert bot._is_stale(123, 6) is True

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_track_task(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        loop = asyncio.new_event_loop()
        task = loop.create_future()
        task.set_result(None)
        bot._track_task(123, task)
        assert task in bot._active_tasks.get(123, set())
        loop.close()


class TestRemoveDownloadFile:
    def _make_bot_with_download(self):
        config = _make_config()
        with (
            patch("music_downloader.telegram.core.app.SpotifyResolver"),
            patch("music_downloader.telegram.core.app.SlskdClient"),
        ):
            bot = MusicBot(config)
        source = os.path.join(config.download_dir, "someuser", "song.flac")
        os.makedirs(os.path.dirname(source))
        with open(source, "w") as f:
            f.write("data")
        return bot, source

    @pytest.mark.asyncio
    async def test_local_delete_skips_slskd(self):
        bot, source = self._make_bot_with_download()
        await bot._remove_download_file(source)
        assert not os.path.exists(source)
        bot.slskd.delete_downloaded_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_none_source_is_noop(self):
        bot, _ = self._make_bot_with_download()
        await bot._remove_download_file(None)
        bot.slskd.delete_downloaded_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_slskd_when_local_delete_fails(self):
        """Read-only DOWNLOAD_DIR: local remove fails, slskd deletes remotely."""
        bot, source = self._make_bot_with_download()
        bot.processor.cleanup_download = MagicMock(return_value=False)

        def _remote_delete(rel_path):
            os.remove(source)
            return True

        bot.slskd.delete_downloaded_file = MagicMock(side_effect=_remote_delete)
        bot.slskd.delete_downloaded_directory = MagicMock(return_value=True)

        await bot._remove_download_file(source)

        bot.slskd.delete_downloaded_file.assert_called_once_with("someuser/song.flac")
        # Parent dir became empty, so the per-user directory is removed remotely too.
        bot.slskd.delete_downloaded_directory.assert_called_once_with("someuser")

    @pytest.mark.asyncio
    async def test_keeps_user_dir_when_not_empty(self):
        bot, source = self._make_bot_with_download()
        sibling = os.path.join(os.path.dirname(source), "other.flac")
        with open(sibling, "w") as f:
            f.write("data")
        bot.processor.cleanup_download = MagicMock(return_value=False)

        def _remote_delete(rel_path):
            os.remove(source)
            return True

        bot.slskd.delete_downloaded_file = MagicMock(side_effect=_remote_delete)
        bot.slskd.delete_downloaded_directory = MagicMock()

        await bot._remove_download_file(source)

        bot.slskd.delete_downloaded_file.assert_called_once_with("someuser/song.flac")
        bot.slskd.delete_downloaded_directory.assert_not_called()

    @pytest.mark.asyncio
    async def test_remote_delete_failure_is_logged_not_raised(self):
        bot, source = self._make_bot_with_download()
        bot.processor.cleanup_download = MagicMock(return_value=False)
        bot.slskd.delete_downloaded_file = MagicMock(return_value=False)
        bot.slskd.delete_downloaded_directory = MagicMock()

        await bot._remove_download_file(source)

        bot.slskd.delete_downloaded_file.assert_called_once()
        bot.slskd.delete_downloaded_directory.assert_not_called()
        assert os.path.exists(source)


# ---------------------------------------------------------------------------
# format_result_reasons
# ---------------------------------------------------------------------------
