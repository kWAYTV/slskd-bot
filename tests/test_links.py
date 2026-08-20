"""Tests for pasted-link parsing and SoundCloud/Spotify link resolution."""

from unittest.mock import MagicMock, patch

import requests

from music_downloader.catalog.links import extract_soundcloud_url, extract_spotify_track_id
from music_downloader.catalog.soundcloud import (
    SoundCloudApi,
    SoundCloudResolver,
    SoundCloudTrack,
    _parse_oembed,
)


def _response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = json_data or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(str(status_code))
    else:
        resp.raise_for_status.return_value = None
    return resp


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

    def test_artist_prefix_in_title_is_stripped(self):
        """SoundCloud titles often embed the artist: 'PÕNKY - REMONTADA by PÕNKY'."""
        track = _parse_oembed({"title": "PÕNKY - REMONTADA by PÕNKY", "author_name": "PÕNKY"})
        assert track == SoundCloudTrack(artist="PÕNKY", title="REMONTADA")

    def test_artist_prefix_case_insensitive(self):
        track = _parse_oembed({"title": "forss – Flickermood by Forss", "author_name": "Forss"})
        assert track == SoundCloudTrack(artist="Forss", title="Flickermood")

    def test_title_equal_to_artist_kept(self):
        track = _parse_oembed({"title": "Forss by Forss", "author_name": "Forss"})
        assert track == SoundCloudTrack(artist="Forss", title="Forss")

    def test_empty_title_returns_none(self):
        assert _parse_oembed({"title": "", "author_name": "x"}) is None

    def test_query_property(self):
        assert SoundCloudTrack(artist="Forss", title="Flickermood").query == "Forss - Flickermood"
        assert SoundCloudTrack(artist="", title="Flickermood").query == "Flickermood"


class TestMatchesSpotifyCandidate:
    def test_same_song_matches(self):
        from music_downloader.catalog.soundcloud import matches_spotify_candidate

        sc = SoundCloudTrack(artist="Forss", title="Flickermood")
        assert matches_spotify_candidate(sc, "Forss", "Flickermood") is True

    def test_different_song_same_artist_rejected(self):
        from music_downloader.catalog.soundcloud import matches_spotify_candidate

        sc = SoundCloudTrack(artist="Ponky", title="Remontada")
        assert matches_spotify_candidate(sc, "Ponky", "Barado") is False

    def test_extended_title_matches(self):
        from music_downloader.catalog.soundcloud import matches_spotify_candidate

        sc = SoundCloudTrack(artist="Ben Sims", title="Manipulated")
        assert matches_spotify_candidate(sc, "Ben Sims", "Manipulated (Original Mix)") is True

    def test_wrong_artist_rejected(self):
        from music_downloader.catalog.soundcloud import matches_spotify_candidate

        sc = SoundCloudTrack(artist="Ponky", title="Remontada")
        assert matches_spotify_candidate(sc, "Someone Else", "Remontada") is False

    def test_no_artist_matches_on_title_alone(self):
        from music_downloader.catalog.soundcloud import matches_spotify_candidate

        sc = SoundCloudTrack(artist="", title="Flickermood")
        assert matches_spotify_candidate(sc, "Forss", "Flickermood") is True


class TestSoundCloudResolver:
    @patch("music_downloader.catalog.soundcloud.requests.get")
    def test_resolve_success_via_oembed(self, mock_get):
        mock_get.return_value = _response(json_data={"title": "Flickermood by Forss", "author_name": "Forss"})
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
        mock_get.return_value = _response(json_data={"title": "Flickermood by Forss", "author_name": "Forss"})
        track = SoundCloudResolver().resolve("https://on.soundcloud.com/AbCd1234")
        assert track is not None
        mock_head.assert_called_once()
        params = mock_get.call_args.kwargs["params"]
        assert params["url"] == "https://soundcloud.com/forss/flickermood"

    def test_no_credentials_means_no_api_client(self):
        assert SoundCloudResolver()._api is None
        assert SoundCloudResolver(client_id="id", client_secret="secret")._api is not None

    def test_official_api_preferred_over_oembed(self):
        resolver = SoundCloudResolver(client_id="id", client_secret="secret")
        resolver._api = MagicMock()
        resolver._api.resolve_track.return_value = SoundCloudTrack(artist="Forss", title="Flickermood")
        track = resolver.resolve("https://soundcloud.com/forss/flickermood")
        assert track == SoundCloudTrack(artist="Forss", title="Flickermood")
        resolver._api.resolve_track.assert_called_once()

    @patch("music_downloader.catalog.soundcloud.requests.get")
    def test_falls_back_to_oembed_when_api_fails(self, mock_get):
        resolver = SoundCloudResolver(client_id="id", client_secret="secret")
        resolver._api = MagicMock()
        resolver._api.resolve_track.return_value = None
        mock_get.return_value = _response(json_data={"title": "Flickermood by Forss", "author_name": "Forss"})
        track = resolver.resolve("https://soundcloud.com/forss/flickermood")
        assert track == SoundCloudTrack(artist="Forss", title="Flickermood")


class TestSoundCloudApi:
    """Official API client — Client Credentials flow + /resolve endpoint."""

    def _token_response(self, token="tok-1", refresh="ref-1"):
        return _response(json_data={"access_token": token, "refresh_token": refresh, "expires_in": 3600})

    def _track_response(self):
        return _response(
            json_data={
                "kind": "track",
                "title": "Flickermood",
                "user": {"username": "Forss"},
                "publisher_metadata": {"artist": "Forss"},
            }
        )

    @patch("music_downloader.catalog.soundcloud.requests.get")
    @patch("music_downloader.catalog.soundcloud.requests.post")
    def test_resolve_track_success(self, mock_post, mock_get):
        mock_post.return_value = self._token_response()
        mock_get.return_value = self._track_response()

        api = SoundCloudApi("id", "secret")
        track = api.resolve_track("https://soundcloud.com/forss/flickermood")

        assert track == SoundCloudTrack(artist="Forss", title="Flickermood")
        assert mock_post.call_args.kwargs["auth"] == ("id", "secret")
        assert mock_post.call_args.kwargs["data"] == {"grant_type": "client_credentials"}
        assert mock_get.call_args.kwargs["headers"] == {"Authorization": "OAuth tok-1"}

    @patch("music_downloader.catalog.soundcloud.requests.get")
    @patch("music_downloader.catalog.soundcloud.requests.post")
    def test_token_is_cached_between_calls(self, mock_post, mock_get):
        mock_post.return_value = self._token_response()
        mock_get.return_value = self._track_response()

        api = SoundCloudApi("id", "secret")
        api.resolve_track("https://soundcloud.com/forss/flickermood")
        api.resolve_track("https://soundcloud.com/forss/flickermood")

        assert mock_post.call_count == 1

    @patch("music_downloader.catalog.soundcloud.requests.get")
    @patch("music_downloader.catalog.soundcloud.requests.post")
    def test_expired_token_renewed_via_refresh_grant(self, mock_post, mock_get):
        mock_post.return_value = self._token_response(token="tok-2", refresh="ref-2")
        mock_get.return_value = self._track_response()

        api = SoundCloudApi("id", "secret")
        api._access_token = "tok-1"
        api._refresh_token = "ref-1"
        api._expires_at = 0  # already expired

        api.resolve_track("https://soundcloud.com/forss/flickermood")
        assert mock_post.call_args.kwargs["data"] == {"grant_type": "refresh_token", "refresh_token": "ref-1"}

    @patch("music_downloader.catalog.soundcloud.requests.get")
    @patch("music_downloader.catalog.soundcloud.requests.post")
    def test_stale_refresh_token_falls_back_to_client_credentials(self, mock_post, mock_get):
        mock_post.side_effect = [_response(status_code=400), self._token_response(token="tok-3")]
        mock_get.return_value = self._track_response()

        api = SoundCloudApi("id", "secret")
        api._refresh_token = "stale"
        api._expires_at = 0

        track = api.resolve_track("https://soundcloud.com/forss/flickermood")
        assert track is not None
        assert mock_post.call_count == 2
        assert mock_post.call_args.kwargs["data"] == {"grant_type": "client_credentials"}

    @patch("music_downloader.catalog.soundcloud.requests.get")
    @patch("music_downloader.catalog.soundcloud.requests.post")
    def test_revoked_token_retries_once_on_401(self, mock_post, mock_get):
        mock_post.side_effect = [self._token_response(token="tok-1"), self._token_response(token="tok-2")]
        mock_get.side_effect = [_response(status_code=401), self._track_response()]

        api = SoundCloudApi("id", "secret")
        track = api.resolve_track("https://soundcloud.com/forss/flickermood")

        assert track is not None
        assert mock_get.call_count == 2
        assert mock_get.call_args.kwargs["headers"] == {"Authorization": "OAuth tok-2"}

    @patch("music_downloader.catalog.soundcloud.requests.get")
    @patch("music_downloader.catalog.soundcloud.requests.post")
    def test_non_track_resource_returns_none(self, mock_post, mock_get):
        mock_post.return_value = self._token_response()
        mock_get.return_value = _response(json_data={"kind": "playlist", "title": "Some Set"})

        api = SoundCloudApi("id", "secret")
        assert api.resolve_track("https://soundcloud.com/forss/sets/x") is None

    @patch("music_downloader.catalog.soundcloud.requests.post")
    def test_token_failure_returns_none(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("boom")
        api = SoundCloudApi("id", "secret")
        assert api.resolve_track("https://soundcloud.com/forss/flickermood") is None

    @patch("music_downloader.catalog.soundcloud.requests.get")
    @patch("music_downloader.catalog.soundcloud.requests.post")
    def test_artist_falls_back_to_uploader(self, mock_post, mock_get):
        mock_post.return_value = self._token_response()
        mock_get.return_value = _response(
            json_data={"kind": "track", "title": "Some Track", "user": {"username": "uploader"}}
        )
        api = SoundCloudApi("id", "secret")
        track = api.resolve_track("https://soundcloud.com/u/t")
        assert track == SoundCloudTrack(artist="uploader", title="Some Track")
