"""Filename/tag identity for the library sweep."""

from slskd_importer.sweep.audit import Audit
from slskd_importer.sweep.identity import identity, parse_stem, strip_junk


def test_classic_artist_title():
    assert parse_stem("Avicii - Wake Me Up") == ("Avicii", "Wake Me Up")


def test_track_prefix_artist_title_with_junk_brackets():
    artist, title = parse_stem("01 - Avicii - Wake Me Up [Digital Media] [FLAC 24bit]")
    assert artist == "Avicii"
    assert title == "Wake Me Up"


def test_artist_album_track_title():
    artist, title = parse_stem("AEREA - 10.000 Flores - 01 10.000 Flores")
    assert artist == "AEREA"
    assert title == "10.000 Flores"


def test_dotted_track_prefix():
    assert parse_stem("03. Daft Punk - One More Time") == ("Daft Punk", "One More Time")


def test_no_separator_fails():
    assert parse_stem("JustAFilename") == ("", "JustAFilename")


def test_tags_win_over_messy_stem():
    audit = Audit(ext="flac", artist="Avicii", title="Wake Me Up", album="True")
    artist, title = identity(audit, "01 - Avicii - Wake Me Up [Digital Media] [FLAC 24bit]")
    assert artist == "Avicii"
    assert title == "Wake Me Up"


def test_falls_back_to_stem_without_tags():
    audit = Audit(ext="flac")
    assert identity(audit, "Artist - Title") == ("Artist", "Title")


def test_strip_junk_keeps_meaningful_brackets():
    assert strip_junk("Song (Live)") == "Song (Live)"
    assert strip_junk("Song [FLAC 24bit]") == "Song"
