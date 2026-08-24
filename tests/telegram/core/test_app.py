"""MusicBot composition: init, helper shims, ranking, per-chat preferences."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from music_downloader.catalog.track import TrackInfo
from music_downloader.soulseek.scoring import rank_responses
from music_downloader.telegram.core.app import MusicBot
from music_downloader.telegram.ui.formatting import format_search_results, format_spotify_results
from tests.telegram.helpers import (
    _make_config,
    _make_search_result,
    _make_track,
)


class TestMusicBotInit:
    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_init(self, mock_slskd, mock_spotify):
        config = _make_config()
        bot = MusicBot(config)
        assert bot.pending == {}
        assert bot.downloads == {}
        assert bot.history_repo is not None


class TestMusicBotHelpers:
    def test_format_results(self):
        track = _make_track()
        results = [_make_search_result(i) for i in range(3)]
        text = format_search_results(track, results)
        assert "Nancy Sinatra" in text
        assert "Bang Bang" in text
        assert "#1" in text
        assert "#3" in text

    def test_format_results_fallback(self):
        track = _make_track()
        results = [_make_search_result()]
        text = format_search_results(track, results, is_fallback=True)
        assert "No FLAC found" in text

    def test_format_results_pagination(self):
        track = _make_track()
        results = [_make_search_result(i) for i in range(15)]
        text = format_search_results(track, results, page=0, page_size=5)
        assert "Page 1/" in text

    def test_format_spotify_results(self):
        tracks = [_make_track() for _ in range(3)]
        text = format_spotify_results(tracks)
        assert "Multiple matches" in text
        assert "Nancy Sinatra" in text

    def test_format_spotify_results_escapes_markdown(self):
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
        text = format_spotify_results(tracks)
        assert "AC\\_DC" in text
        assert "Hells\\*Bells" in text
        # ']' is not special in Markdown V1; only '[' needs the escape.
        assert "Back\\[in]Black" in text

    def test_format_spotify_results_pagination(self):
        tracks = [_make_track() for _ in range(12)]
        text = format_spotify_results(tracks, page=0, page_size=5)
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
    def test_flac_found(self):
        """When FLAC results exist, returns them with is_fallback=False."""
        track = _make_track()
        flac_result = [_make_search_result()]
        scorer = MagicMock()
        scorer.score_results = MagicMock(return_value=flac_result)
        ranked, is_fallback = rank_responses([], track, scorer)
        assert len(ranked) == 1
        assert is_fallback is False

    def test_non_flac_fallback(self):
        """When only non-FLAC exists, returns with is_fallback=True."""
        track = _make_track()
        mp3_result = [_make_search_result()]
        scorer = MagicMock()
        # First call (flac_only=True) returns nothing scored, second call returns results
        scorer.score_results = MagicMock(side_effect=[[], mp3_result])
        ranked, is_fallback = rank_responses([], track, scorer)
        assert len(ranked) == 1
        assert is_fallback is True

    def test_no_results(self):
        """When no results match, returns empty list."""
        track = _make_track()
        scorer = MagicMock()
        scorer.score_results = MagicMock(return_value=[])
        ranked, is_fallback = rank_responses([], track, scorer)
        assert ranked == []
        assert is_fallback is False

    def test_max_duration_diff_passed(self):
        """max_duration_diff should be forwarded to score_results."""
        track = _make_track()
        scorer = MagicMock()
        scorer.score_results = MagicMock(return_value=[_make_search_result()])
        rank_responses([], track, scorer, max_duration_diff=120)
        call_kwargs = scorer.score_results.call_args[1]
        assert call_kwargs["max_duration_diff"] == 120


# ---------------------------------------------------------------------------
# Import pending separation tests
# ---------------------------------------------------------------------------


class TestPerChatQualityPref:
    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_quality_defaults_to_config(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.quality_preference = "cd"
        bot = MusicBot(config)
        assert bot.quality_pref(67890) == "cd"
        assert bot.quality_pref(11111) == "cd"

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_override_beats_default(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._quality_overrides[67890] = "cd"
        assert bot.quality_pref(67890) == "cd"
        assert bot.quality_pref(11111) == "hires"

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_quality_reloaded_from_db(self, mock_slskd, mock_spotify):
        config = _make_config()
        bot = MusicBot(config)
        bot.prefs_repo.set_quality(67890, "cd")
        restarted = MusicBot(config)
        assert restarted.quality_pref(67890) == "cd"
        assert restarted.quality_pref(11111) == "hires"

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    def test_download_semaphore(self, mock_slskd, mock_spotify):
        import asyncio

        config = _make_config()
        config.max_concurrent_downloads = 2
        bot = MusicBot(config)
        assert isinstance(bot._download_sem, asyncio.Semaphore)
        assert bot._download_sem._value == 2
