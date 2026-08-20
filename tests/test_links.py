"""Tests for pasted-link parsing and SoundCloud/Spotify link resolution."""

from unittest.mock import MagicMock, patch

import requests

from music_downloader.catalog.links import extract_soundcloud_url, extract_spotify_track_id
from music_downloader.catalog.soundcloud import SoundCloudResolver, SoundCloudTrack, _parse_oembed


class TestSpotifyTrackLinks:
    def test_standard_track_url(self):
        url = "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC?si=abc123"
        assert extract_spotify_track_id(url) == "4uLU6hMCjMI75M1A2tKUQC"

    def test_intl_track_url(self):
        url = "https://open.spotify.com/intl-es/track/4uLU6hMCjMI75M1A2tKUQC"
        assert extract_spotify_track_id(url) == "4uLU6hMCjMI75M1A2tKUQC"

    def test_track_uri(self):
        assert extract_spotify_track_id("spotify:track:4uLU6hMCjMI75M1A2tKUQC") == "4uLU6hMCjMI75M1A2tKUQC"

    def test_playlist_url_is_not_a_track(self):
        assert extract_spotify_track_id("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M") is None

    def test_plain_text_is_not_a_track(self):
        assert extract_spotify_track_id("nancy sinatra bang bang") is None


class TestSoundCloudLinks:
    def test_track_url(self):
        url = "https://soundcloud.com/forss/flickermood"
        assert extract_soundcloud_url(url) == url

    def test_mobile_and_www_urls(self):
        assert extract_soundcloud_url("https://www.soundcloud.com/forss/flickermood") is not None
        assert extract_soundcloud_url("https://m.soundcloud.com/forss/flickermood") is not None

    def test_short_link(self):
        url = "https://on.soundcloud.com/AbCd1234"
        assert extract_soundcloud_url(url) == url

    def test_set_url_is_not_a_track(self):
        assert extract_soundcloud_url("https://soundcloud.com/forss/sets/soulhack") is None

    def test_profile_text_is_not_a_track(self):
        assert extract_soundcloud_url("check out soundcloud sometime") is None


class TestParseOembed:
    def test_title_with_by_author_suffix(self):
        track = _parse_oembed({"title": "Flickermood by Forss", "author_name": "Forss"})
        assert track == SoundCloudTrack(artist="Forss", title="Flickermood")

    def test_title_without_suffix(self):
        track = _parse_oembed({"title": "Some Track", "author_name": "Uploader"})
        assert track == SoundCloudTrack(artist="Uploader", title="Some Track")

    def test_empty_title_returns_none(self):
        assert _parse_oembed({"title": "", "author_name": "x"}) is None

    def test_query_property(self):
        assert SoundCloudTrack(artist="Forss", title="Flickermood").query == "Forss - Flickermood"
        assert SoundCloudTrack(artist="", title="Flickermood").query == "Flickermood"


class TestSoundCloudResolver:
    @patch("music_downloader.catalog.soundcloud.requests.get")
    def test_resolve_success(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"title": "Flickermood by Forss", "author_name": "Forss"},
        )
        track = SoundCloudResolver().resolve("https://soundcloud.com/forss/flickermood")
        assert track == SoundCloudTrack(artist="Forss", title="Flickermood")
        params = mock_get.call_args.kwargs["params"]
        assert params["url"] == "https://soundcloud.com/forss/flickermood"

    @patch("music_downloader.catalog.soundcloud.requests.get")
    def test_resolve_network_error_returns_none(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")
        assert SoundCloudResolver().resolve("https://soundcloud.com/forss/flickermood") is None

    @patch("music_downloader.catalog.soundcloud.requests.head")
    @patch("music_downloader.catalog.soundcloud.requests.get")
    def test_short_link_is_expanded_first(self, mock_get, mock_head):
        mock_head.return_value = MagicMock(url="https://soundcloud.com/forss/flickermood")
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"title": "Flickermood by Forss", "author_name": "Forss"},
        )
        track = SoundCloudResolver().resolve("https://on.soundcloud.com/AbCd1234")
        assert track is not None
        mock_head.assert_called_once()
        params = mock_get.call_args.kwargs["params"]
        assert params["url"] == "https://soundcloud.com/forss/flickermood"
