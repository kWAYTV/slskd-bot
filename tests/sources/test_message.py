"""A chat message read as a tracklist: typed lines, links, mixes of both."""

from unittest.mock import MagicMock, patch

import pytest

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.sources.message import read_message, resolve_link
from slskd_importer.sources.spotify import is_spotify_url, resolve_spotify
from slskd_importer.sources.text import clean_line, entries_from_lines
from slskd_importer.sources.tracklist import Entry, SourceError, Tracklist

MESSAGE = "slskd_importer.sources.message"
TRACK = TrackInfo("Nancy Sinatra", "Bang Bang", "Album", 162_000, "https://open.spotify.com/track/abc", "1966")


@pytest.mark.parametrize(
    ("line", "cleaned"),
    [
        ("Nancy Sinatra - Bang Bang", "Nancy Sinatra - Bang Bang"),
        ("01. Nancy Sinatra - Bang Bang", "Nancy Sinatra - Bang Bang"),
        ("3) Nancy Sinatra - Bang Bang", "Nancy Sinatra - Bang Bang"),
        ("07 - Nancy Sinatra - Bang Bang", "Nancy Sinatra - Bang Bang"),
        ("[12:30] Nancy Sinatra - Bang Bang [Reprise]", "Nancy Sinatra - Bang Bang"),
        ("1:02:45 Nancy Sinatra - Bang Bang", "Nancy Sinatra - Bang Bang"),
        ("• Nancy Sinatra - Bang Bang", "Nancy Sinatra - Bang Bang"),
        ("311 - Down", "311 - Down"),
        ("99 luftballons", "99 luftballons"),
        ("   ", ""),
    ],
)
def test_clean_line(line, cleaned):
    assert clean_line(line) == cleaned


def test_entries_drop_blanks_unidentified_and_repeats():
    lines = ["A - B", "", "ID - ID", "a - b", "Artist - ID", "Unknown", "C - D"]
    assert [e.query for e in entries_from_lines(lines)] == ["A - B", "Unknown", "C - D"]


def test_single_line_is_a_track():
    tracklist = read_message("daft punk one more time", MagicMock())
    assert (tracklist.kind, tracklist.name) == ("track", "daft punk one more time")
    assert tracklist.entries == [Entry(query="daft punk one more time")]


def test_many_lines_are_a_list():
    tracklist = read_message("A - B\nC - D\n\nE - F", MagicMock())
    assert (tracklist.kind, tracklist.name, len(tracklist.entries)) == ("list", "3 tracks", 3)


def test_one_link_keeps_the_source_name():
    source = Tracklist("Summer Set", "playlist", "https://x", [Entry(query="A - B"), Entry(query="C - D")])
    with patch(f"{MESSAGE}.resolve_link", return_value=source) as resolve:
        tracklist = read_message("check this https://www.youtube.com/playlist?list=PL1.", MagicMock())
    assert resolve.call_args.args[0] == "https://www.youtube.com/playlist?list=PL1"
    assert (tracklist.name, tracklist.kind, len(tracklist.entries)) == ("Summer Set", "playlist", 2)


def test_links_and_lines_merge():
    source = Tracklist("Set", "mix", "https://x", [Entry(query="A - B")])
    with patch(f"{MESSAGE}.resolve_link", return_value=source):
        tracklist = read_message("https://soundcloud.com/x/sets/y\nC - D", MagicMock())
    assert tracklist.kind == "list" and [e.label for e in tracklist.entries] == ["A - B", "C - D"]


def test_failed_link_alone_raises_its_reason():
    with (
        patch(f"{MESSAGE}.resolve_link", side_effect=SourceError("blocked")),
        pytest.raises(SourceError, match="blocked"),
    ):
        read_message("https://www.1001tracklists.com/tracklist/x", MagicMock())


def test_failed_link_does_not_lose_the_typed_lines():
    with patch(f"{MESSAGE}.resolve_link", side_effect=SourceError("blocked")):
        assert read_message("https://example.com/x\nA - B", MagicMock()).entries == [Entry(query="A - B")]


def test_empty_message():
    with pytest.raises(SourceError):
        read_message("  \n ", MagicMock())


def test_resolve_link_routes_by_source():
    spotify = MagicMock()
    with (
        patch(f"{MESSAGE}.resolve_spotify") as by_spotify,
        patch(f"{MESSAGE}.resolve_media") as by_media,
        patch(f"{MESSAGE}.resolve_tracklist_page") as by_page,
    ):
        resolve_link("https://open.spotify.com/album/abc", spotify)
        resolve_link("https://www.youtube.com/watch?v=abc", spotify)
        resolve_link("https://www.1001tracklists.com/tracklist/abc/some-set.html", spotify)
    by_spotify.assert_called_once()
    by_media.assert_called_once()
    by_page.assert_called_once()
    with pytest.raises(SourceError, match="example.com"):
        resolve_link("https://example.com/song", spotify)


def test_spotify_track_link():
    spotify = MagicMock()
    spotify.get_track.return_value = TRACK
    tracklist = resolve_spotify("https://open.spotify.com/intl-es/track/abc123", spotify)
    assert tracklist.kind == "track" and tracklist.entries == [Entry(track=TRACK)]
    spotify.get_track.return_value = None
    with pytest.raises(SourceError):
        resolve_spotify("spotify:track:abc123", spotify)


def test_spotify_album_link():
    info = MagicMock(tracks=[TRACK, TRACK], is_album=True)
    info.name = "Album"
    with patch("slskd_importer.sources.spotify.PlaylistResolver") as resolver:
        resolver.is_spotify_url.return_value = True
        resolver.return_value.resolve.return_value = info
        tracklist = resolve_spotify("https://open.spotify.com/album/abc", MagicMock())
        assert (tracklist.name, tracklist.kind, len(tracklist.entries)) == ("Album", "album", 2)
        resolver.return_value.resolve.return_value = None
        with pytest.raises(SourceError):
            resolve_spotify("https://open.spotify.com/playlist/abc", MagicMock())


def test_is_spotify_url():
    assert is_spotify_url("https://open.spotify.com/track/abc")
    assert is_spotify_url("https://open.spotify.com/playlist/abc")
    assert not is_spotify_url("https://www.youtube.com/watch?v=abc")
