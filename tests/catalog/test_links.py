"""Tests for pasted-link detection (Spotify track links, SoundCloud track URLs)."""

from music_downloader.catalog.links import extract_soundcloud_url, extract_spotify_track_id


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
