"""Soulseek search for a resolved track, with tier fallbacks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from slskd_importer.telegram.core.app import MusicBot
from slskd_importer.telegram.search.soulseek import notify_if_already_owned
from tests.telegram.download.helpers import _make_config, _make_context, _make_result, _make_track


class TestNotifyIfAlreadyOwned:
    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_not_owned_sends_nothing(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())
        bot.processor.find_exact = MagicMock(return_value=[])
        bot.history_repo.find_success = MagicMock(return_value=None)
        context = _make_context()
        await notify_if_already_owned(bot, context, 123, _make_track())
        context.bot.send_message.assert_not_called()

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_owned_sends_notice_without_blocking(self, mock_slskd_cls, mock_spotify):
        bot = MusicBot(_make_config())
        bot.processor.find_exact = MagicMock(return_value=["Nancy Sinatra - Bang Bang.flac"])
        bot.history_repo.find_success = MagicMock(return_value=None)
        context = _make_context()
        await notify_if_already_owned(bot, context, 123, _make_track())
        context.bot.send_message.assert_called_once()
        text = context.bot.send_message.call_args.kwargs["text"]
        assert "Already in the library" in text
        # No keyboard — purely informational.
        assert "reply_markup" not in context.bot.send_message.call_args.kwargs


class TestDoSlskdSearch:
    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
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

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
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
        assert any(s.chat_id == 123 and s.results for s in bot.pending.values())

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
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

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
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
        assert not any(s.results for s in bot.pending.values())

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
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

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_slskd_unavailable_message(self, mock_slskd_cls, mock_spotify):
        from slskd_importer.soulseek.errors import SlskdUnavailableError

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
        assert "slskd is unreachable" in edited
