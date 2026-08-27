"""Spotify candidate lookup and filtering."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.telegram.core.app import MusicBot
from slskd_importer.telegram.core.session import PendingSearch
from tests.telegram.helpers import (
    _make_config,
    _make_context,
    _make_track,
    _make_update,
)


class TestMusicBotDoSearch:
    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_no_spotify_results(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.spotify = MagicMock()
        bot.spotify.search_multiple = MagicMock(return_value=[])
        update = _make_update()
        context = _make_context()
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        context.bot.send_message = AsyncMock(return_value=msg)
        await bot._do_search(update, context, "nonexistent song", "1")

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_single_spotify_result(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.spotify = MagicMock()
        bot.spotify.search_multiple = MagicMock(return_value=[_make_track()])
        bot._do_slskd_search = AsyncMock()
        update = _make_update()
        context = _make_context()
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        context.bot.send_message = AsyncMock(return_value=msg)
        await bot._do_search(update, context, "Nancy Sinatra Bang Bang", "1")
        bot._do_slskd_search.assert_called_once()

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_multiple_spotify_results(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        tracks = [_make_track(), _make_track()]
        tracks[1].album = "Different Album"
        bot.spotify = MagicMock()
        bot.spotify.search_multiple = MagicMock(return_value=tracks)
        update = _make_update()
        context = _make_context()
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        context.bot.send_message = AsyncMock(return_value=msg)
        await bot._do_search(update, context, "Nancy Sinatra Bang Bang", "1")
        assert "1" in bot._spotify_candidates

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_stale_search_aborted(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.spotify = MagicMock()
        bot.spotify.search_multiple = MagicMock(return_value=[_make_track()])
        bot._do_slskd_search = AsyncMock()
        update = _make_update()
        context = _make_context()
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        context.bot.send_message = AsyncMock(return_value=msg)
        bot.pending["1"] = PendingSearch(query="test", chat_id=67890, search_id="1", cancelled=True)
        await bot._do_search(update, context, "test", "1")
        bot._do_slskd_search.assert_not_called()

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_exception_handled(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.spotify = MagicMock()
        bot.spotify.search_multiple = MagicMock(side_effect=Exception("API error"))
        update = _make_update()
        context = _make_context()
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        context.bot.send_message = AsyncMock(return_value=msg)
        await bot._do_search(update, context, "test", "1")
        # Should not raise

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_artist_filter(self, mock_slskd, mock_spotify):
        """When query has 'Artist - Title', filter by artist."""
        bot = MusicBot(_make_config())
        t1 = _make_track()
        t2 = TrackInfo(
            artist="Other Artist", title="Bang Bang", album="X", duration_ms=162000, spotify_url="", year="2024"
        )
        bot.spotify = MagicMock()
        bot.spotify.search_multiple = MagicMock(return_value=[t1, t2])
        bot._do_slskd_search = AsyncMock()
        update = _make_update()
        context = _make_context()
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        context.bot.send_message = AsyncMock(return_value=msg)
        await bot._do_search(update, context, "Nancy Sinatra - Bang Bang", "1")
        # Should filter to only Nancy Sinatra -> single result -> auto slskd search
        bot._do_slskd_search.assert_called_once()
