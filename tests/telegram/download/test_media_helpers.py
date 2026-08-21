"""Async media wrappers: FLAC analysis, OGG, previews, artwork."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from music_downloader.library.flac import FlacVerdict
from music_downloader.telegram.core.app import MusicBot
from tests.telegram.download.helpers import _make_config, _make_track


class TestAsyncHelpers:
    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_analyze_flac_runs(self, mock_slskd_cls, mock_spotify):
        with patch("music_downloader.telegram.download.delivery.analyze_flac") as mock_analyze:
            mock_analyze.return_value = FlacVerdict(
                verdict="AUTHENTIC",
                cutoff_khz=22.05,
                nyquist_khz=22.05,
                sample_rate=44100,
                bit_depth=16,
            )
            result = await MusicBot._analyze_flac("/fake/path.flac")
            assert result is not None
            assert result.verdict == "AUTHENTIC"

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_analyze_flac_exception(self, mock_slskd_cls, mock_spotify):
        with patch("music_downloader.telegram.download.delivery.analyze_flac") as mock_analyze:
            mock_analyze.side_effect = Exception("read error")
            result = await MusicBot._analyze_flac("/fake/path.flac")
            assert result is None

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_convert_to_ogg_runs(self, mock_slskd_cls, mock_spotify):
        with patch("music_downloader.telegram.download.delivery.convert_to_ogg") as mock_conv:
            mock_conv.return_value = "/tmp/output.ogg"
            result = await MusicBot._convert_to_ogg("/fake/path.flac")
            assert result == "/tmp/output.ogg"

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_convert_to_ogg_exception(self, mock_slskd_cls, mock_spotify):
        with patch("music_downloader.telegram.download.delivery.convert_to_ogg") as mock_conv:
            mock_conv.side_effect = Exception("ffmpeg error")
            result = await MusicBot._convert_to_ogg("/fake/path.flac")
            assert result is None

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_create_preview_runs(self, mock_slskd_cls, mock_spotify):
        with patch("music_downloader.telegram.download.delivery.create_preview_clip") as mock_clip:
            mock_clip.return_value = "/tmp/preview.ogg"
            result = await MusicBot._create_preview("/fake/path.flac", 60.0)
            assert result == "/tmp/preview.ogg"

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_create_preview_exception(self, mock_slskd_cls, mock_spotify):
        with patch("music_downloader.telegram.download.delivery.create_preview_clip") as mock_clip:
            mock_clip.side_effect = Exception("ffmpeg error")
            result = await MusicBot._create_preview("/fake/path.flac")
            assert result is None

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_embed_spotify_artwork_success(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())
        with patch("music_downloader.telegram.download.delivery.fetch_spotify_artwork") as mock_fetch:
            mock_fetch.return_value = b"\xff\xd8\xff\xe0"
            with patch("music_downloader.telegram.download.delivery.embed_artwork_into_file") as mock_embed:
                mock_embed.return_value = True
                await bot._embed_spotify_artwork("/fake/path.flac", _make_track())

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_embed_spotify_artwork_no_art(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())
        with patch("music_downloader.telegram.download.delivery.fetch_spotify_artwork") as mock_fetch:
            mock_fetch.return_value = None
            await bot._embed_spotify_artwork("/fake/path.flac", _make_track())

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_embed_spotify_artwork_exception(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())
        with patch("music_downloader.telegram.download.delivery.fetch_spotify_artwork") as mock_fetch:
            mock_fetch.side_effect = Exception("network error")
            # Should not raise
            await bot._embed_spotify_artwork("/fake/path.flac", _make_track())
