"""Query helper edge cases: non-Latin scripts, keyword extraction, title cleaning."""

from __future__ import annotations

from slskd_importer.soulseek.query import clean_search_title as _clean_search_title
from slskd_importer.soulseek.query import extract_latin_keywords as _extract_latin_keywords
from slskd_importer.soulseek.query import has_non_latin_script as _has_non_latin_script


class TestHasNonLatinScript:
    def test_latin_only(self):
        assert _has_non_latin_script("Hello World") is False

    def test_cjk(self):
        assert _has_non_latin_script("紅") is True

    def test_cyrillic(self):
        assert _has_non_latin_script("Привет") is True

    def test_mixed(self):
        assert _has_non_latin_script("紅 - KURENAI") is True

    def test_empty(self):
        assert _has_non_latin_script("") is False

    def test_numbers_only(self):
        assert _has_non_latin_script("12345") is False


class TestExtractLatinKeywords:
    def test_mixed_script(self):
        result = _extract_latin_keywords("紅 - KURENAI - Single Long Version")
        assert "KURENAI" in result
        # Noise words should be filtered
        assert "Single" not in result
        assert "Long" not in result
        assert "Version" not in result

    def test_all_noise(self):
        result = _extract_latin_keywords("The Single Version Mix")
        assert result == []

    def test_pure_latin(self):
        result = _extract_latin_keywords("Purple Rain")
        assert "Purple" in result
        assert "Rain" in result

    def test_short_words_filtered(self):
        result = _extract_latin_keywords("I Am A Star")
        # Single-char words filtered by {2,} regex
        assert "Star" in result


class TestCleanSearchTitleExtended:
    def test_deluxe_edition(self):
        assert _clean_search_title("Song - Deluxe Edition") == "Song"

    def test_anniversary_edition(self):
        assert _clean_search_title("Song - Anniversary Edition") == "Song"

    def test_super_deluxe(self):
        assert _clean_search_title("Song - Super Deluxe") == "Song"

    def test_paren_mono(self):
        assert _clean_search_title("Song (Mono)") == "Song"

    def test_paren_stereo(self):
        assert _clean_search_title("Song (Stereo)") == "Song"

    def test_year_mix(self):
        assert _clean_search_title("Song (2009 Mix)") == "Song"


# ---------------------------------------------------------------------------
# MusicBot tests
# ---------------------------------------------------------------------------
