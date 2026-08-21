"""MusicBot composition: init, helper shims, ranking, per-chat preferences."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from music_downloader.catalog.track import TrackInfo
from music_downloader.telegram.core.app import MusicBot
from tests.telegram.helpers import (
    _make_config,
    _make_context,
    _make_search_result,
    _make_track,
    _make_update,
)


class TestMusicBotInit:
    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_init(self, mock_slskd, mock_spotify):
        config = _make_config()
        bot = MusicBot(config)
        assert bot.auto_mode is False
        assert bot.pending == {}
        assert bot.downloads == {}
        assert bot.history_repo is not None


class TestMusicBotHelpers:
    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_format_results(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        track = _make_track()
        results = [_make_search_result(i) for i in range(3)]
        text = bot._format_results(track, results)
        assert "Nancy Sinatra" in text
        assert "Bang Bang" in text
        assert "#1" in text
        assert "#3" in text

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_format_results_fallback(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        track = _make_track()
        results = [_make_search_result()]
        text = bot._format_results(track, results, is_fallback=True)
        assert "No FLAC found" in text

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_format_results_pagination(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        track = _make_track()
        results = [_make_search_result(i) for i in range(15)]
        text = bot._format_results(track, results, page=0, page_size=5)
        assert "Page 1/" in text

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_format_spotify_results(self, mock_slskd, mock_spotify):
        tracks = [_make_track() for _ in range(3)]
        text = MusicBot._format_spotify_results(tracks)
        assert "Multiple matches" in text
        assert "Nancy Sinatra" in text

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_format_spotify_results_escapes_markdown(self, mock_slskd, mock_spotify):
        tracks = [
            TrackInfo(
                artist="AC_DC",
                title="Hells*Bells",
                album="Back[in]Black",
                duration_ms=312_000,
                spotify_url="https://open.spotify.com/track/xxx",
                year="1980",
            )
        ]
        text = MusicBot._format_spotify_results(tracks)
        assert "AC\\_DC" in text
        assert "Hells\\*Bells" in text
        # ']' is not special in Markdown V1; only '[' needs the escape.
        assert "Back\\[in]Black" in text

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_format_spotify_results_pagination(self, mock_slskd, mock_spotify):
        tracks = [_make_track() for _ in range(12)]
        text = MusicBot._format_spotify_results(tracks, page=0, page_size=5)
        assert "page 1/" in text

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_add_history(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        track = _make_track()
        result = _make_search_result()
        await bot._add_history(track, result, "success")
        assert bot.history_repo.count() == 1
        records = bot.history_repo.get_recent(1)
        assert records[0].status == "success"

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_add_history_persists_multiple(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        track = _make_track()
        result = _make_search_result()
        for _ in range(55):
            await bot._add_history(track, result, "success")
        assert bot.history_repo.count() == 55

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_next_dl_id(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        id1 = bot._next_dl_id()
        id2 = bot._next_dl_id()
        assert id1 != id2
        assert id1 == "1"
        assert id2 == "2"


class TestRankResponses:
    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_flac_found(self, mock_slskd, mock_spotify):
        """When FLAC results exist, returns them with is_fallback=False."""
        bot = MusicBot(_make_config())
        track = _make_track()
        flac_result = [_make_search_result()]
        bot.slskd.parse_results = MagicMock(side_effect=[flac_result])
        bot.scorer.score_results = MagicMock(return_value=flac_result)
        ranked, is_fallback = bot._rank_responses([], track)
        assert len(ranked) == 1
        assert is_fallback is False

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_non_flac_fallback(self, mock_slskd, mock_spotify):
        """When only non-FLAC exists, returns with is_fallback=True."""
        bot = MusicBot(_make_config())
        track = _make_track()
        mp3_result = [_make_search_result()]
        # First call (flac_only=True) returns nothing scored, second call returns results
        bot.slskd.parse_results = MagicMock(side_effect=[[], mp3_result])
        bot.scorer.score_results = MagicMock(side_effect=[[], mp3_result])
        ranked, is_fallback = bot._rank_responses([], track)
        assert len(ranked) == 1
        assert is_fallback is True

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_no_results(self, mock_slskd, mock_spotify):
        """When no results match, returns empty list."""
        bot = MusicBot(_make_config())
        track = _make_track()
        bot.slskd.parse_results = MagicMock(return_value=[])
        bot.scorer.score_results = MagicMock(return_value=[])
        ranked, is_fallback = bot._rank_responses([], track)
        assert ranked == []
        assert is_fallback is False

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_max_duration_diff_passed(self, mock_slskd, mock_spotify):
        """max_duration_diff should be forwarded to score_results."""
        bot = MusicBot(_make_config())
        track = _make_track()
        bot.slskd.parse_results = MagicMock(return_value=[_make_search_result()])
        bot.scorer.score_results = MagicMock(return_value=[_make_search_result()])
        bot._rank_responses([], track, max_duration_diff=120)
        call_kwargs = bot.scorer.score_results.call_args[1]
        assert call_kwargs["max_duration_diff"] == 120


# ---------------------------------------------------------------------------
# Import pending separation tests
# ---------------------------------------------------------------------------


class TestPerChatAutoMode:
    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_is_auto_defaults_to_config(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.auto_mode = True
        bot = MusicBot(config)
        assert bot.is_auto(67890) is True
        assert bot.is_auto(11111) is True

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_override_beats_default(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._auto_overrides[67890] = True
        assert bot.is_auto(67890) is True
        assert bot.is_auto(11111) is False

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_auto_reflects_chat_override(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._auto_overrides[67890] = True
        update = _make_update()
        context = _make_context()
        await bot.cmd_auto(update, context)
        assert "ON" in update.message.reply_text.call_args[0][0]
