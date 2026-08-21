"""Tests for pasted-link detection (Spotify track links)."""

from music_downloader.catalog.links import extract_spotify_track_id


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
