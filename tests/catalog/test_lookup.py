"""Catalog lookup: fielded search first, artist filter, edition collapsing, text fallback."""

from unittest.mock import MagicMock

from slskd_importer.catalog.lookup import collapse_editions, filter_candidates, find_candidates, identify
from slskd_importer.catalog.track import TrackInfo


def track(artist="Daft Punk", title="One More Time", album="Discovery", secs=320, year="2001"):
    return TrackInfo(artist, title, album, secs * 1000, "", year)


def test_fielded_search_wins_for_separated_queries():
    spotify = MagicMock()
    spotify.search_fielded.return_value = [track()]
    assert find_candidates(spotify, "Daft Punk - One More Time") == [track()]
    spotify.search_fielded.assert_called_once_with("Daft Punk", "One More Time", 50)
    spotify.search_multiple.assert_not_called()


def test_free_text_when_no_separator_or_fielded_is_empty():
    spotify = MagicMock()
    spotify.search_fielded.return_value = []
    spotify.search_multiple.return_value = [track()]
    assert find_candidates(spotify, "daft punk one more time") == [track()]
    spotify.search_fielded.assert_not_called()
    assert find_candidates(spotify, "Daft Punk - One More Time (Official Video)") == [track()]
    spotify.search_multiple.assert_called_with("Daft Punk - One More Time", 50)


def test_identify_keeps_the_typed_song_when_the_catalog_returns_another():
    spotify = MagicMock()
    spotify.search_fielded.return_value = []
    spotify.search_multiple.return_value = [track(artist="Some Pop Star", title="Hit Single")]
    found = identify(spotify, "William Marqs - no.0101")
    assert (found.artist, found.title, found.duration_ms) == ("William Marqs", "No.0101", 0)


def test_identify_uses_the_catalog_track_when_it_is_the_typed_song():
    spotify = MagicMock()
    remix = track(title="One More Time - Extended Remix", secs=500)
    spotify.search_fielded.return_value = [remix, track(title="One More Time - Original Mix")]
    found = identify(spotify, "daft punk - one more time")
    assert found.title == "One More Time - Original Mix" and found.duration_ms == 320_000


def test_identify_without_separator_takes_the_best_candidate():
    spotify = MagicMock()
    spotify.search_multiple.return_value = [track()]
    assert identify(spotify, "daft punk one more time") == track()


def test_identify_falls_back_to_the_text():
    spotify = MagicMock()
    spotify.search_fielded.return_value = []
    spotify.search_multiple.return_value = []
    found = identify(spotify, "some dj - unreleased id")
    assert (found.artist, found.title, found.duration_ms) == ("Some Dj", "Unreleased Id", 0)


def test_collapse_editions_keeps_the_earliest_release():
    reissue = track(album="Greatest Hits", secs=321, year="2010")
    remix = track(title="One More Time", secs=500, year="2005")
    assert collapse_editions([reissue, track(), remix]) == [track(), remix]


def test_filter_prefers_the_named_artist_and_drops_others():
    cover = track(artist="Tribute Band")
    assert filter_candidates("Daft Punk - One More Time", [cover, track()]) == [track()]


def test_filter_falls_back_when_the_artist_filter_empties_the_list():
    cover = track(artist="Tribute Band")
    assert filter_candidates("Daft Pnk - One More Time", [cover, cover]) == [cover]
