"""Pasted Spotify link handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from slskd_importer.telegram.core.app import MusicBot
from tests.telegram.helpers import (
    _make_config,
    _make_context,
    _make_track,
    _make_update,
)


class TestLinkQueries:
    def _make_bot(self):
        with (
            patch("slskd_importer.telegram.core.app.SpotifyResolver"),
            patch("slskd_importer.telegram.core.app.SlskdClient"),
        ):
            return MusicBot(_make_config())

    @pytest.mark.asyncio
    async def test_spotify_track_link_resolves_directly(self):
        from slskd_importer.telegram.search import links as search_links

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
        assert any(s.track is not None and s.chat_id == 67890 for s in bot.pending.values())

    @pytest.mark.asyncio
    async def test_playlist_link_starts_import(self):
        from slskd_importer.telegram.search import links as search_links

        bot = self._make_bot()
        bot._check_library_auth = AsyncMock(return_value=True)
        url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        update = _make_update(text=url)
        context = _make_context()

        with patch("slskd_importer.telegram.search.links.start_import_from_url", new_callable=AsyncMock) as mock_start:
            handled = await search_links.handle_link_query(bot, update, context, 67890, url)
        assert handled is True
        mock_start.assert_awaited_once()
        assert mock_start.await_args.args[4] == url

    @pytest.mark.asyncio
    async def test_playlist_link_requires_library_access(self):
        from slskd_importer.telegram.search import links as search_links

        bot = self._make_bot()
        bot._check_library_auth = AsyncMock(return_value=False)
        url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        update = _make_update(text=url)
        context = _make_context()

        with patch("slskd_importer.telegram.search.links.start_import_from_url", new_callable=AsyncMock) as mock_start:
            handled = await search_links.handle_link_query(bot, update, context, 67890, url)
        assert handled is True
        mock_start.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_plain_text_is_not_handled(self):
        from slskd_importer.telegram.search import links as search_links

        bot = self._make_bot()
        update = _make_update(text="nancy sinatra bang bang")
        context = _make_context()

        handled = await search_links.handle_link_query(bot, update, context, 67890, "nancy sinatra bang bang")
        assert handled is False


# ---------------------------------------------------------------------------
# /quality and /undo commands
# ---------------------------------------------------------------------------
