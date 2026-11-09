"""Query helper edge cases: non-Latin scripts, keyword extraction, title cleaning."""

from __future__ import annotations

from slskd_importer.soulseek.query import clean_query, parse_query_artist_title, smart_case
from slskd_importer.soulseek.query import clean_search_title as _clean_search_title
from slskd_importer.soulseek.query import extract_latin_keywords as _extract_latin_keywords
from slskd_importer.soulseek.query import has_non_latin_script as _has_non_latin_script


class TestCleanQuery:
    def test_strips_video_title_brackets(self):
        assert clean_query("Nancy Sinatra - Bang Bang (Official Video)") == "Nancy Sinatra - Bang Bang"
        assert clean_query("Tool - Lateralus [HD]") == "Tool - Lateralus"
        assert clean_query("Song (Lyrics)") == "Song"
        assert clean_query("Song (Official Audio) [4K]") == "Song"

    def test_strips_bare_tail(self):
        assert clean_query("tool - lateralus official audio") == "tool - lateralus"
        assert clean_query("artist title lyrics") == "artist title"

    def test_keeps_meaningful_brackets(self):
        assert clean_query("Radiohead - Creep (Live)") == "Radiohead - Creep (Live)"
        assert clean_query("Bang Bang (My Baby Shot Me Down)") == "Bang Bang (My Baby Shot Me Down)"

    def test_strips_outer_quotes_and_spaces(self):
        assert clean_query('  "Heroes"  ') == "Heroes"
        assert clean_query("a   b") == "a b"

    def test_never_returns_empty(self):
        assert clean_query("(Official Video)") == "(Official Video)"


class TestSmartCase:
    def test_capitalizes_lowercase(self):
        assert smart_case("david bowie") == "David Bowie"
        assert smart_case("don't stop") == "Don't Stop"

    def test_preserves_mixed_case(self):
        assert smart_case("AC/DC") == "AC/DC"
        assert smart_case("Paul McCartney") == "Paul McCartney"
        assert smart_case("DJ Shadow") == "DJ Shadow"


class TestParseQueryArtistTitle:
    def test_hyphen_separator(self):
        assert parse_query_artist_title("nancy sinatra - bang bang") == ("Nancy Sinatra", "Bang Bang")

    def test_en_dash_em_dash_and_pipe(self):
        assert parse_query_artist_title("AC/DC – Back In Black") == ("AC/DC", "Back In Black")
        assert parse_query_artist_title("AC/DC — Back In Black") == ("AC/DC", "Back In Black")
        assert parse_query_artist_title("Daft Punk | One More Time") == ("Daft Punk", "One More Time")

    def test_hyphen_inside_word_is_not_a_separator(self):
        assert parse_query_artist_title("jay-z encore") == ("Jay-z", "Encore")

    def test_last_word_fallback(self):
        assert parse_query_artist_title("david bowie helden") == ("David Bowie", "Helden")
        assert parse_query_artist_title("bowie helden") == ("Bowie", "Helden")
        assert parse_query_artist_title("helden") == ("", "Helden")

    def test_noise_is_cleaned_first(self):
        assert parse_query_artist_title("Tool - Lateralus (Official Video)") == ("Tool", "Lateralus")

    def test_preserves_typed_casing(self):
        assert parse_query_artist_title("Nancy Sinatra - Bang Bang") == ("Nancy Sinatra", "Bang Bang")


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
