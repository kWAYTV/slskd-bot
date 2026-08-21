"""Soulseek search for a resolved track, with tier fallbacks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from music_downloader.telegram.core.app import MusicBot
from tests.telegram.download.helpers import _make_config, _make_context, _make_result, _make_track


class TestDoSlskdSearch:
    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_no_results_all_fallbacks(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())
        bot.slskd = AsyncMock()
        bot.slskd.search = AsyncMock(return_value=[])
        bot.scorer = MagicMock()
        bot.scorer.score_results = MagicMock(return_value=[])
        bot._chat_generation[123] = 0

        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        msg.message_id = 1

        context = _make_context()
        await bot._do_slskd_search(context, 123, _make_track(), msg, 0)
        # Should have tried multiple fallback searches

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_finds_flac_results(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())
        bot.slskd = AsyncMock()
        bot.slskd.search = AsyncMock(return_value=[{"responses": []}])
        results = [_make_result(0), _make_result(1)]
        bot.scorer = MagicMock()
        bot.scorer.score_results = MagicMock(return_value=results)
        bot._chat_generation[123] = 0

        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        msg.message_id = 1

        context = _make_context()
        await bot._do_slskd_search(context, 123, _make_track(), msg, 0)
        assert 123 in bot.pending

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_non_flac_fallback(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())
        bot.slskd = AsyncMock()
        bot.slskd.search = AsyncMock(return_value=[])
        score_count = 0

        def score_side_effect(results, track, **kwargs):
            nonlocal score_count
            score_count += 1
            return results if results else []

        bot.scorer = MagicMock()
        bot.scorer.score_results = MagicMock(side_effect=score_side_effect)
        bot._chat_generation[123] = 0

        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        msg.message_id = 1

        context = _make_context()
        await bot._do_slskd_search(context, 123, _make_track(), msg, 0)

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_stale_aborts_early(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())
        bot.slskd = AsyncMock()
        bot.slskd.search = AsyncMock(return_value=[])
        bot.scorer = MagicMock()
        bot.scorer.score_results = MagicMock(return_value=[])
        bot._chat_generation[123] = 5  # generation is ahead

        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        msg.message_id = 1

        context = _make_context()
        await bot._do_slskd_search(context, 123, _make_track(), msg, 0)
        assert 123 not in bot.pending

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_exception_handled(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())
        bot.slskd = AsyncMock()
        bot.slskd.search = AsyncMock(side_effect=Exception("Network error"))
        bot._chat_generation[123] = 0

        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        msg.message_id = 1

        context = _make_context()
        await bot._do_slskd_search(context, 123, _make_track(), msg, 0)
        # Should not raise

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_auto_mode_downloads_best_match(self, mock_slskd_cls, mock_spotify):
        config = _make_config()
        config.auto_mode = True
        bot = MusicBot(config)
        bot.auto_mode = True
        bot.slskd = AsyncMock()
        bot.slskd.search = AsyncMock(return_value=[{"responses": []}])
        results = [_make_result(0), _make_result(1)]
        bot.scorer = MagicMock()
        bot.scorer.score_results = MagicMock(return_value=results)
        bot._chat_generation[123] = 0
        bot._do_download = AsyncMock()

        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        msg.message_id = 1

        context = _make_context()

        def _close_coro(coro, **kwargs):
            coro.close()
            return MagicMock()

        context.application.create_task = MagicMock(side_effect=_close_coro)
        await bot._do_slskd_search(context, 123, _make_track(), msg, 0)
        assert 123 in bot.pending
        context.application.create_task.assert_called_once()
        edited = " ".join(str(c) for c in msg.edit_text.call_args_list)
        assert "Auto-download" in edited

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_slskd_unavailable_message(self, mock_slskd_cls, mock_spotify):
        from music_downloader.soulseek.errors import SlskdUnavailableError

        bot = MusicBot(_make_config())
        bot.slskd = AsyncMock()
        bot.slskd.search = AsyncMock(side_effect=SlskdUnavailableError("down"))
        bot._chat_generation[123] = 0

        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        msg.message_id = 1

        context = _make_context()
        await bot._do_slskd_search(context, 123, _make_track(), msg, 0)
        edited = " ".join(str(c) for c in msg.edit_text.call_args_list)
        assert "Cannot reach slskd" in edited
