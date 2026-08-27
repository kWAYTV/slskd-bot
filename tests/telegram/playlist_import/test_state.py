"""Import pending state is separate from manual search state."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from slskd_importer.telegram.core.app import MusicBot
from slskd_importer.telegram.core.session import PendingSearch
from tests.telegram.helpers import (
    _make_config,
    _make_search_result,
    _make_track,
)


class TestImportPendingSeparation:
    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    def test_import_pending_does_not_clobber_regular(self, mock_slskd, mock_spotify):
        """Import flow should use _import_pending, not overwrite self.pending."""
        bot = MusicBot(_make_config())
        track = _make_track()
        results = [_make_search_result()]
        # Simulate active regular search
        bot.pending["1"] = PendingSearch(query="regular", track=track, results=results, chat_id=67890, search_id="1")
        # Simulate import storing its state
        bot._import_pending[67890] = PendingSearch(query="import", track=track, results=results)
        # Regular search should be untouched
        assert bot.pending["1"].query == "regular"
        assert bot._import_pending[67890].query == "import"

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cancel_clears_import_pending(self, mock_slskd, mock_spotify):
        """Cancellation should clear both pending dicts."""
        bot = MusicBot(_make_config())
        track = _make_track()
        bot.pending["1"] = PendingSearch(query="q", track=track, results=[], chat_id=67890, search_id="1")
        bot._import_pending[67890] = PendingSearch(query="i", track=track, results=[])
        await bot._cancel_chat_operations(67890)
        assert "1" not in bot.pending
        assert 67890 not in bot._import_pending


# ---------------------------------------------------------------------------
# Import callback routing tests
# ---------------------------------------------------------------------------
