"""Pasted Spotify link handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
