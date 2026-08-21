"""Pasted Spotify/SoundCloud link handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from music_downloader.catalog.track import TrackInfo
from music_downloader.telegram.core.app import MusicBot
from tests.telegram.helpers import (
    _make_config,
    _make_context,
    _make_track,
    _make_update,
)


class TestLinkQueries:
    def _make_bot(self):
        with (
            patch("music_downloader.telegram.core.app.SpotifyResolver"),
            patch("music_downloader.telegram.core.app.SlskdClient"),
        ):
            return MusicBot(_make_config())

    @pytest.mark.asyncio
    async def test_spotify_track_link_resolves_directly(self):
        from music_downloader.telegram.search import links as search_links

        bot = self._make_bot()
        bot.spotify.get_track = MagicMock(return_value=_make_track())
        bot._do_slskd_search = AsyncMock()
        update = _make_update(text="https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC")
        context = _make_context()

        handled = await search_links.handle_link_query(
            bot, update, context, 67890, "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"
        )
        assert handled is True
        bot.spotify.get_track.assert_called_once_with("4uLU6hMCjMI75M1A2tKUQC")
        bot._do_slskd_search.assert_awaited_once()
        assert bot.pending[67890].track is not None

    @pytest.mark.asyncio
    async def test_soundcloud_link_uses_verified_spotify_match(self):
        from music_downloader.catalog.soundcloud import SoundCloudTrack
        from music_downloader.telegram.search import links as search_links

        bot = self._make_bot()
        bot.soundcloud.resolve = MagicMock(return_value=SoundCloudTrack(artist="Forss", title="Flickermood"))
        spotify_match = TrackInfo(
            artist="Forss",
            title="Flickermood",
            album="Soulhack",
            duration_ms=222000,
            spotify_url="https://x",
            year="2003",
        )
        bot.spotify.search_multiple = MagicMock(return_value=[spotify_match])
        bot._do_slskd_search = AsyncMock()
        update = _make_update(text="https://soundcloud.com/forss/flickermood")
        context = _make_context()

        handled = await search_links.handle_link_query(
            bot, update, context, 67890, "https://soundcloud.com/forss/flickermood"
        )
        assert handled is True
        bot.soundcloud.resolve.assert_called_once_with("https://soundcloud.com/forss/flickermood")
        bot._do_slskd_search.assert_awaited_once()
        assert bot._do_slskd_search.await_args.args[2] is spotify_match

    @pytest.mark.asyncio
    async def test_soundcloud_track_not_on_spotify_searches_directly(self):
        """A wrong same-artist Spotify hit must not replace the SoundCloud track."""
        from music_downloader.catalog.soundcloud import SoundCloudTrack
        from music_downloader.telegram.search import links as search_links

        bot = self._make_bot()
        bot.soundcloud.resolve = MagicMock(return_value=SoundCloudTrack(artist="Ponky", title="Remontada"))
        wrong_track = TrackInfo(
            artist="Ponky",
            title="Barado",
            album="Fire Ritual EP",
            duration_ms=342000,
            spotify_url="https://x",
            year="2024",
        )
        bot.spotify.search_multiple = MagicMock(return_value=[wrong_track])
        bot._do_slskd_search = AsyncMock()
        bot._do_direct_slskd_search = AsyncMock()
        update = _make_update(text="https://soundcloud.com/ponky/remontada")
        context = _make_context()

        handled = await search_links.handle_link_query(
            bot, update, context, 67890, "https://soundcloud.com/ponky/remontada"
        )
        assert handled is True
        bot._do_slskd_search.assert_not_awaited()
        bot._do_direct_slskd_search.assert_awaited_once()
        assert bot._do_direct_slskd_search.await_args.args[2] == "Ponky Remontada"
        display_track = bot._do_direct_slskd_search.await_args.kwargs["display_track"]
        assert display_track.artist == "Ponky"
        assert display_track.title == "Remontada"

    @pytest.mark.asyncio
    async def test_playlist_link_suggests_import(self):
        from music_downloader.telegram.search import links as search_links

        bot = self._make_bot()
        update = _make_update(text="https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
        context = _make_context()

        handled = await search_links.handle_link_query(
            bot, update, context, 67890, "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        )
        assert handled is True
        text = update.message.reply_text.call_args.args[0]
        assert "/import" in text

    @pytest.mark.asyncio
    async def test_plain_text_is_not_handled(self):
        from music_downloader.telegram.search import links as search_links

        bot = self._make_bot()
        update = _make_update(text="nancy sinatra bang bang")
        context = _make_context()

        handled = await search_links.handle_link_query(bot, update, context, 67890, "nancy sinatra bang bang")
        assert handled is False


# ---------------------------------------------------------------------------
# /quality and /undo commands
# ---------------------------------------------------------------------------
