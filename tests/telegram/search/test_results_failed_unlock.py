"""Failed picks unlock the results keyboard so another # is tappable."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from slskd_importer.telegram.core.session import PendingSearch
from slskd_importer.telegram.search.results import render_results_card
from tests.telegram.helpers import _make_config, _make_search_result, _make_track


@patch("slskd_importer.telegram.core.app.SpotifyResolver")
@patch("slskd_importer.telegram.core.app.SlskdClient")
def test_failed_pick_keeps_result_buttons(_mock_slskd, _mock_spotify):
    from slskd_importer.telegram.core.app import MusicBot

    bot = MusicBot(_make_config())
    bot.t = MagicMock(side_effect=lambda _chat, key, **kw: kw.get("chip") or kw.get("label") or key)
    bot.locale = MagicMock(return_value="en")
    results = [_make_search_result(0), _make_search_result(1)]
    pending = PendingSearch(
        query="q",
        track=_make_track(),
        results=results,
        chat_id=1,
        search_id="s1",
        picked_index=1,
        pick_state="failed",
    )

    _text, markup = render_results_card(bot, pending)
    callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "dl:s1:0" in callbacks
    assert "dl:s1:1" in callbacks
    assert not any(c.startswith("lock:") for c in callbacks)
