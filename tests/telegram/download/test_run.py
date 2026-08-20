"""The download run: transfer, verify, deliver, approval prompt."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from music_downloader.library.flac import FlacVerdict
from music_downloader.soulseek.result import DownloadStatus
from music_downloader.telegram.core.app import MusicBot
from tests.telegram.download.helpers import _make_config, _make_context, _make_result, _make_track


class TestDoDownload:
    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_enqueue_fails(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())
        bot.slskd = MagicMock()
        bot.slskd.enqueue_download = MagicMock(return_value=False)

        status_msg = AsyncMock()
        status_msg.edit_text = AsyncMock()
        status_msg.message_id = 1

        context = _make_context()
        await bot._do_download(context, 123, _make_track(), _make_result(), status_msg)

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_download_failed_status(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())
        bot.slskd = MagicMock()
        bot.slskd.enqueue_download = MagicMock(return_value=True)
        failed_status = DownloadStatus(username="u", filename="f", state="Errored")
        bot.slskd.wait_for_download = AsyncMock(return_value=failed_status)

        status_msg = AsyncMock()
        status_msg.edit_text = AsyncMock()
        status_msg.message_id = 1

        context = _make_context()
        await bot._do_download(context, 123, _make_track(), _make_result(), status_msg)
        records = bot.history_repo.get_recent(1)
        assert any(r.status == "failed" for r in records)

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_download_timeout(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())
        bot.slskd = MagicMock()
        bot.slskd.enqueue_download = MagicMock(return_value=True)
        bot.slskd.wait_for_download = AsyncMock(return_value=None)

        status_msg = AsyncMock()
        status_msg.edit_text = AsyncMock()
        status_msg.message_id = 1

        context = _make_context()
        await bot._do_download(context, 123, _make_track(), _make_result(), status_msg)

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_file_not_found_on_disk(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())
        bot.slskd = MagicMock()
        bot.slskd.enqueue_download = MagicMock(return_value=True)
        completed = DownloadStatus(username="u", filename="f", state="Completed, Succeeded")
        bot.slskd.wait_for_download = AsyncMock(return_value=completed)
        bot.processor = MagicMock()
        bot.processor.find_downloaded_file = MagicMock(return_value=None)

        status_msg = AsyncMock()
        status_msg.edit_text = AsyncMock()
        status_msg.message_id = 1

        context = _make_context()
        await bot._do_download(context, 123, _make_track(), _make_result(), status_msg)
        records = bot.history_repo.get_recent(1)
        assert any(r.status == "file_not_found" for r in records)

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_successful_download_small_file(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())
        bot.slskd = MagicMock()
        bot.slskd.enqueue_download = MagicMock(return_value=True)
        completed = DownloadStatus(username="u", filename="f", state="Completed, Succeeded")
        bot.slskd.wait_for_download = AsyncMock(return_value=completed)

        # Create a real small temp file
        with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as f:
            f.write(b"\x00" * 1000)
            source_path = f.name

        try:
            bot.processor = MagicMock()
            bot.processor.find_downloaded_file = MagicMock(return_value=source_path)
            bot.processor.build_filename = MagicMock(return_value="Artist - Song.flac")
            bot._analyze_flac = AsyncMock(
                return_value=FlacVerdict(
                    verdict="AUTHENTIC",
                    cutoff_khz=22.05,
                    nyquist_khz=22.05,
                    sample_rate=44100,
                    bit_depth=16,
                )
            )

            status_msg = AsyncMock()
            status_msg.edit_text = AsyncMock()
            status_msg.message_id = 1

            sent_msg = AsyncMock()
            sent_msg.message_id = 2

            context = _make_context()
            context.bot.send_audio = AsyncMock(return_value=sent_msg)

            result = _make_result()
            await bot._do_download(context, 123, _make_track(), result, status_msg)
            context.bot.send_audio.assert_called_once()
        finally:
            os.unlink(source_path)

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_send_audio_bad_request_falls_back_to_document(self, mock_slskd_cls, mock_spotify):
        from telegram.error import BadRequest

        bot = MusicBot(_make_config())
        bot.slskd = MagicMock()
        bot.slskd.enqueue_download = MagicMock(return_value=True)
        completed = DownloadStatus(username="u", filename="f", state="Completed, Succeeded")
        bot.slskd.wait_for_download = AsyncMock(return_value=completed)

        with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as f:
            f.write(b"\x00" * 1000)
            source_path = f.name

        try:
            bot.processor = MagicMock()
            bot.processor.find_downloaded_file = MagicMock(return_value=source_path)
            bot.processor.build_filename = MagicMock(return_value="Artist - Song.flac")
            bot._analyze_flac = AsyncMock(return_value=None)

            status_msg = AsyncMock()
            status_msg.edit_text = AsyncMock()
            status_msg.message_id = 1

            sent_msg = AsyncMock()
            sent_msg.message_id = 2

            context = _make_context()
            context.bot.send_audio = AsyncMock(side_effect=BadRequest("file too large"))
            context.bot.send_document = AsyncMock(return_value=sent_msg)

            await bot._do_download(context, 123, _make_track(), _make_result(), status_msg)
            context.bot.send_document.assert_called_once()
        finally:
            os.unlink(source_path)

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_download_exception(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())
        bot.slskd = MagicMock()
        bot.slskd.enqueue_download = MagicMock(side_effect=Exception("unexpected"))

        status_msg = AsyncMock()
        status_msg.edit_text = AsyncMock()
        status_msg.message_id = 1

        context = _make_context()
        await bot._do_download(context, 123, _make_track(), _make_result(), status_msg)

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_non_flac_skips_analysis(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())
        bot.slskd = MagicMock()
        bot.slskd.enqueue_download = MagicMock(return_value=True)
        completed = DownloadStatus(username="u", filename="f", state="Completed")
        bot.slskd.wait_for_download = AsyncMock(return_value=completed)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"\x00" * 1000)
            source_path = f.name

        try:
            bot.processor = MagicMock()
            bot.processor.find_downloaded_file = MagicMock(return_value=source_path)
            bot.processor.build_filename = MagicMock(return_value="Artist - Song.mp3")
            bot._analyze_flac = AsyncMock()

            status_msg = AsyncMock()
            status_msg.edit_text = AsyncMock()
            status_msg.message_id = 1

            sent_msg = AsyncMock()
            sent_msg.message_id = 2
            context = _make_context()
            context.bot.send_audio = AsyncMock(return_value=sent_msg)

            mp3_result = _make_result(ext="mp3")
            await bot._do_download(context, 123, _make_track(), mp3_result, status_msg)
            bot._analyze_flac.assert_not_called()
        finally:
            os.unlink(source_path)
