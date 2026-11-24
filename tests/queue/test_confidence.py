"""A copy is taken unasked only when its path names the song."""

import pytest

from slskd_importer.catalog.names import normalize, same_artist, same_title
from slskd_importer.catalog.track import TrackInfo
from slskd_importer.queue.confidence import names_the_song
from slskd_importer.soulseek.result import SearchResult


def song(artist: str, title: str) -> TrackInfo:
    return TrackInfo(artist, title, "", 0, "", "")


@pytest.mark.parametrize(
    ("artist", "title", "path", "sure"),
    [
        ("Kodaman", "Ulkā", "\\techno\\Kodaman - Ulka.flac", True),
        ("William Marqs", "no.0101", "\\VA\\03 William Marqs - no.0101 (Original Mix).wav", True),
        ("Low Blow", "Time To Love (Extended Mix)", "\\x\\Low Blow - Time To Love (Extended Mix).aiff", True),
        ("Low Blow", "Time To Love (Extended Mix)", "\\x\\Low Blow - Time To Love.flac", False),
        ("UMEK", "Gatex", "\\UMEK\\Gatex EP\\01 Gatex.flac", True),  # artist only in the folder
        ("Phil Berg", "Void", "\\other\\Someone Else - Void.flac", False),
        ("Phil Berg", "Void", "\\Phil Berg\\Another Track.flac", False),
        ("", "Void", "\\x\\Void.flac", True),
    ],
)
def test_names_the_song(artist, title, path, sure):
    assert names_the_song(song(artist, title), SearchResult(username="u", filename=path, size=1)) is sure


def test_name_comparisons():
    assert normalize("Ain’t Nobody — Shake It!") == "aint nobody shake it"
    assert same_artist("camelphat", "camelphat and elderbrook")
    assert same_title(normalize("Void"), normalize("Void - Original Mix"))
    assert not same_title(normalize("Losing It"), normalize("Losing It (Extended Mix)"))
    assert not same_title(normalize("Void"), normalize("Original Mix"))


def test_letters_without_an_accent_form_compare_as_their_plain_spelling():
    assert normalize("BACKBØNE") == "backbone"
    assert normalize("DHÆÜR") == "dhaeur"
    track = song("BACKBØNE", "Permanent Pressure")
    assert names_the_song(track, SearchResult("u", "\\Backbone - Pressure EP\\01. Permanent Pressure.flac", 1))
