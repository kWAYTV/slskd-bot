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


def _edition(title="Bang Bang", album="Album", duration_ms=162_000, year="1966", artist="Nancy Sinatra"):
    return TrackInfo(artist=artist, title=title, album=album, duration_ms=duration_ms, spotify_url="", year=year)


class TestFilterCandidates:
    def test_collapses_same_recording_across_albums_keeping_earliest(self):
        from slskd_importer.telegram.search.spotify import _filter_candidates

        tracks = [
            _edition(album="Greatest Hits", year="1998"),
            _edition(album="How Does That Grab You?", year="1966"),
            _edition(album="Reissue", duration_ms=163_000, year="2009"),
        ]
        out = _filter_candidates("nancy sinatra bang bang", tracks)
        assert len(out) == 1
        assert out[0].album == "How Does That Grab You?"

    def test_keeps_different_versions(self):
        from slskd_importer.telegram.search.spotify import _filter_candidates

        tracks = [
            _edition(),
            _edition(title="Bang Bang - Live", duration_ms=200_000),
            _edition(duration_ms=240_000, album="Extended"),
        ]
        out = _filter_candidates("nancy sinatra bang bang", tracks)
        assert len(out) == 3

    def test_en_dash_query_filters_by_artist(self):
        from slskd_importer.telegram.search.spotify import _filter_candidates

        tracks = [_edition(), _edition(artist="Cher", album="X")]
        out = _filter_candidates("Nancy Sinatra – Bang Bang", tracks)
        assert [t.artist for t in out] == ["Nancy Sinatra"]


class TestMusicBotDoSearch:
    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_no_spotify_results_falls_through_to_direct_search(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.spotify = MagicMock()
        bot.spotify.search_multiple = MagicMock(return_value=[])
        bot._do_direct_slskd_search = AsyncMock()
        update = _make_update()
        context = _make_context()
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        context.bot.send_message = AsyncMock(return_value=msg)
        await bot._do_search(update, context, "nonexistent song", "1")
        bot._do_direct_slskd_search.assert_awaited_once()
        assert bot._do_direct_slskd_search.await_args.kwargs["search_id"] == "1"
        edited = msg.edit_text.call_args.args[0]
        assert "Save as" in edited and "Nonexistent" in edited
        assert msg.edit_text.call_args.kwargs.get("reply_markup") is None

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_separator_query_uses_fielded_search_first(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.spotify = MagicMock()
        bot.spotify.search_fielded = MagicMock(return_value=[_make_track()])
        bot.spotify.search_multiple = MagicMock(return_value=[])
        bot._do_slskd_search = AsyncMock()
        update = _make_update()
        context = _make_context()
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        context.bot.send_message = AsyncMock(return_value=msg)
        await bot._do_search(update, context, "Nancy Sinatra - Bang Bang (Official Video)", "1")
        bot.spotify.search_fielded.assert_called_once_with("Nancy Sinatra", "Bang Bang", 50)
        bot.spotify.search_multiple.assert_not_called()
        bot._do_slskd_search.assert_called_once()

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_fielded_miss_falls_back_to_free_text(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.spotify = MagicMock()
        bot.spotify.search_fielded = MagicMock(return_value=[])
        bot.spotify.search_multiple = MagicMock(return_value=[_make_track()])
        bot._do_slskd_search = AsyncMock()
        update = _make_update()
        context = _make_context()
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        context.bot.send_message = AsyncMock(return_value=msg)
        await bot._do_search(update, context, "Nancy Sinatra - Bang Bang", "1")
        bot.spotify.search_multiple.assert_called_once_with("Nancy Sinatra - Bang Bang", 50)
        bot._do_slskd_search.assert_called_once()

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
        tracks[1].duration_ms = 200_000  # a genuinely different version, not a reissue
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
        bot.spotify.search_fielded = MagicMock(return_value=[])
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
