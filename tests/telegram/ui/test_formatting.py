"""Progress bar and result formatting."""

from __future__ import annotations

from slskd_importer.telegram.ui.formatting import progress_bar
from tests.telegram.helpers import (
    _make_search_result,
    _make_track,
)


class TestProgressBar:
    def test_zero_percent(self):
        assert progress_bar(0) == "▱" * 10

    def test_full(self):
        assert progress_bar(100) == "▰" * 10

    def test_half(self):
        assert progress_bar(50) == "▰" * 5 + "▱" * 5

    def test_clamps_out_of_range(self):
        assert progress_bar(-5) == "▱" * 10
        assert progress_bar(150) == "▰" * 10

    def test_custom_width(self):
        assert progress_bar(50, width=4) == "▰▰▱▱"


class TestFormatResultReasons:
    def test_full_reasons_line(self):
        from slskd_importer.telegram.ui.formatting import format_result_reasons

        track = _make_track()  # 162s reference
        result = _make_search_result()
        result.length = 162
        result.has_free_slot = True
        result.score = 87.4
        line = format_result_reasons(track, result)
        assert "exact duration" in line
        assert "free slot" in line
        assert "87/100" in line

    def test_duration_diff_and_queue(self):
        from slskd_importer.telegram.ui.formatting import format_result_reasons

        track = _make_track()
        result = _make_search_result()
        result.length = 165
        result.has_free_slot = False
        result.queue_length = 3
        result.score = 60.0
        line = format_result_reasons(track, result)
        assert "±3s" in line
        assert "queue of 3" in line

    def test_no_reference_duration(self):
        from slskd_importer.telegram.ui.formatting import format_result_reasons

        track = _make_track()
        track.duration_ms = 0
        result = _make_search_result()
        result.score = 0
        result.has_free_slot = False
        result.queue_length = 0
        assert format_result_reasons(track, result) == ""


# ---------------------------------------------------------------------------
# format_search_results
# ---------------------------------------------------------------------------


class TestFormatSearchResults:
    def test_direct_search_fallback_does_not_claim_flac(self):
        """Direct search (no reference duration) must honor is_fallback: an MP3
        fallback list used to be headlined 'Found N FLAC matches'."""
        from slskd_importer.telegram.ui.formatting import format_search_results

        track = _make_track()
        track.duration_ms = 0  # direct search marker
        result = _make_search_result()
        result.filename = "\\Music\\Nancy Sinatra - Bang Bang.mp3"

        text = format_search_results(track, [result], is_fallback=True)
        assert "FLAC match" not in text
        assert "No FLAC found" in text
        assert "[MP3]" in text

    def test_direct_search_flac_header(self):
        from slskd_importer.telegram.ui.formatting import format_search_results

        track = _make_track()
        track.duration_ms = 0
        text = format_search_results(track, [_make_search_result()], is_fallback=False)
        assert "Found 1 FLAC match" in text

    def test_spotify_search_fallback_header_unchanged(self):
        from slskd_importer.telegram.ui.formatting import format_search_results

        track = _make_track()
        result = _make_search_result()
        result.filename = "\\Music\\Nancy Sinatra - Bang Bang.mp3"
        text = format_search_results(track, [result], is_fallback=True)
        assert "No FLAC found" in text
        assert "FLAC match" not in text

    def test_shows_remote_parent_folder(self):
        from slskd_importer.telegram.ui.formatting import format_search_results

        result = _make_search_result()
        result.filename = "\\Music\\2009 Remaster 24-96\\Track.flac"
        text = format_search_results(_make_track(), [result])
        assert "2009 Remaster 24-96" in text

    def test_soulseek_folder_specials_use_code_span(self):
        """Folders with `_` / `[` must not be wrapped in italic — Telegram MD V1
        cannot close `_foo_bar_` and the results edit then silently fails."""
        from slskd_importer.telegram.ui.formatting import format_search_results
        from slskd_importer.telegram.ui.markdown import code_span

        result = _make_search_result()
        result.filename = "\\@@abc\\Oscar_Mulero_-_Curation_One_[WEB_FLAC]\\01 - Reaction Pair.flac"
        text = format_search_results(_make_track(), [result])
        folder = "Oscar_Mulero_-_Curation_One_[WEB_FLAC]"
        assert code_span(folder) in text
        assert f"_{folder}_" not in text
        assert "_Oscar_Mulero" not in text

    def test_highlights_picked_row_and_status(self):
        from slskd_importer.telegram.ui.formatting import format_search_results

        result = _make_search_result()
        text = format_search_results(
            _make_track(),
            [result],
            picked_index=0,
            pick_state="downloading",
            status_line="⬇️ Downloading #1 · Nancy Sinatra — Bang Bang",
        )
        assert "*#1*  ⬇️" in text
        assert "Downloading #1" in text


class TestTrackChip:
    def test_with_label(self):
        from slskd_importer.telegram.ui.formatting import track_chip

        assert track_chip(_make_track(), "#2") == "#2 · Nancy Sinatra — Bang Bang"

    def test_without_label(self):
        from slskd_importer.telegram.ui.formatting import track_chip

        assert track_chip(_make_track()) == "Nancy Sinatra — Bang Bang"


# ---------------------------------------------------------------------------
# Pasted link handling
# ---------------------------------------------------------------------------
