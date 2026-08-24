"""Large-file delivery: OGG conversion and preview fallback."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from slskd_importer.telegram.core.app import MusicBot
from tests.telegram.download.helpers import _make_config, _make_context, _make_result, _make_track


class TestSendLargeFile:
    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_ogg_conversion_success_small_enough(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(b"\x00" * 1000)
            ogg_path = f.name

        try:
            bot._convert_to_ogg = AsyncMock(return_value=ogg_path)
            bot.processor = MagicMock()
            bot.processor.build_filename = MagicMock(return_value="Artist - Song.ogg")

            sent_msg = AsyncMock()
            sent_msg.message_id = 2
            context = _make_context()
            context.bot.send_audio = AsyncMock(return_value=sent_msg)

            await bot._send_large_file(
                context,
                123,
                _make_track(),
                _make_result(),
                "/fake/source.flac",
                60_000_000,
                "Quality line",
                "#1",
                "dl1",
            )
            context.bot.send_audio.assert_called_once()
        finally:
            if os.path.exists(ogg_path):
                os.unlink(ogg_path)

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_ogg_too_large_falls_back_to_preview(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())

        # Create a fake "large" OGG (we'll mock the size check)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(b"\x00" * 100)
            ogg_path = f.name

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(b"\x00" * 100)
            preview_path = f.name

        try:
            bot._convert_to_ogg = AsyncMock(return_value=ogg_path)
            bot._create_preview = AsyncMock(return_value=preview_path)
            bot.processor = MagicMock()
            bot.processor.build_filename = MagicMock(return_value="Artist - Song.ogg")

            sent_msg = AsyncMock()
            sent_msg.message_id = 2
            context = _make_context()
            context.bot.send_audio = AsyncMock(return_value=sent_msg)

            # Patch os.path.getsize to return large size for OGG
            orig_getsize = os.path.getsize

            def mock_getsize(path):
                if path == ogg_path:
                    return 60_000_000  # > 50MB limit
                return orig_getsize(path)

            with patch("slskd_importer.telegram.download.delivery.os.path.getsize", side_effect=mock_getsize):
                await bot._send_large_file(
                    context,
                    123,
                    _make_track(),
                    _make_result(),
                    "/fake/source.flac",
                    70_000_000,
                    "Quality",
                    "#1",
                    "dl1",
                )
        finally:
            for p in (ogg_path, preview_path):
                if os.path.exists(p):
                    os.unlink(p)

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_ogg_conversion_fails_uses_preview(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(b"\x00" * 100)
            preview_path = f.name

        try:
            bot._convert_to_ogg = AsyncMock(return_value=None)
            bot._create_preview = AsyncMock(return_value=preview_path)
            bot.processor = MagicMock()
            bot.processor.build_filename = MagicMock(return_value="Artist - Song.ogg")

            sent_msg = AsyncMock()
            sent_msg.message_id = 2
            context = _make_context()
            context.bot.send_audio = AsyncMock(return_value=sent_msg)

            await bot._send_large_file(
                context,
                123,
                _make_track(),
                _make_result(),
                "/fake/source.flac",
                60_000_000,
                "Quality",
                "#1",
                "dl1",
            )
        finally:
            if os.path.exists(preview_path):
                os.unlink(preview_path)

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_both_conversions_fail(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())
        bot._convert_to_ogg = AsyncMock(return_value=None)
        bot._create_preview = AsyncMock(return_value=None)

        sent_msg = AsyncMock()
        sent_msg.message_id = 2
        context = _make_context()
        context.bot.send_message = AsyncMock(return_value=sent_msg)

        await bot._send_large_file(
            context,
            123,
            _make_track(),
            _make_result(),
            "/fake/source.flac",
            60_000_000,
            "Quality",
            "#1",
            "dl1",
        )
        context.bot.send_message.assert_called_once()
