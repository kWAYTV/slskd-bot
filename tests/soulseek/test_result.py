"""Tests for Soulseek search and download value objects."""

from slskd_importer.soulseek.result import DownloadStatus, SearchResult


class TestSearchResult:
    """Test SearchResult dataclass properties."""

    def test_basename_with_backslash(self):
        r = SearchResult(username="u", filename="\\Music\\Artist\\Song.flac", size=100)
        assert r.basename == "Song.flac"

    def test_basename_no_backslash(self):
        r = SearchResult(username="u", filename="Song.flac", size=100)
        assert r.basename == "Song.flac"

    def test_basename_posix_path(self):
        r = SearchResult(username="u", filename="/Music/Artist/Song.flac", size=100)
        assert r.basename == "Song.flac"

    def test_basename_mixed_separators(self):
        r = SearchResult(username="u", filename="\\Music/Artist\\Song.flac", size=100)
        assert r.basename == "Song.flac"

    def test_parent_dir_windows_path(self):
        r = SearchResult(username="u", filename="\\Music\\2009 Remaster\\Song.flac", size=100)
        assert r.parent_dir == "2009 Remaster"

    def test_parent_dir_bare_filename(self):
        r = SearchResult(username="u", filename="Song.flac", size=100)
        assert r.parent_dir == ""

    def test_extension(self):
        r = SearchResult(username="u", filename="\\Music\\Song.flac", size=100)
        assert r.extension == "flac"

    def test_extension_mp3(self):
        r = SearchResult(username="u", filename="\\Music\\Song.MP3", size=100)
        assert r.extension == "mp3"

    def test_extension_no_dot(self):
        r = SearchResult(username="u", filename="noextension", size=100)
        assert r.extension == ""

    def test_duration_display_valid(self):
        r = SearchResult(username="u", filename="f.flac", size=100, length=185)
        assert r.duration_display == "3:05"

    def test_duration_display_none(self):
        r = SearchResult(username="u", filename="f.flac", size=100, length=None)
        assert r.duration_display == "??:??"

    def test_duration_display_zero(self):
        r = SearchResult(username="u", filename="f.flac", size=100, length=0)
        assert r.duration_display == "??:??"

    def test_size_mb(self):
        r = SearchResult(username="u", filename="f.flac", size=52_428_800)
        assert r.size_mb == 50.0

    def test_quality_display_full(self):
        r = SearchResult(
            username="u",
            filename="f.flac",
            size=100,
            bit_depth=24,
            sample_rate=96000,
            bit_rate=2000,
        )
        assert "24bit" in r.quality_display
        assert "96.0kHz" in r.quality_display
        assert "2000kbps" in r.quality_display

    def test_quality_display_bitrate_only(self):
        r = SearchResult(
            username="u",
            filename="f.flac",
            size=100,
            bit_rate=320,
        )
        assert r.quality_display == "320kbps"

    def test_quality_display_no_info(self):
        r = SearchResult(username="u", filename="f.flac", size=100)
        assert r.quality_display == "FLAC"

    def test_quality_display_no_info_uses_extension(self):
        r = SearchResult(username="u", filename="f.wav", size=100)
        assert r.quality_display == "WAV"

    def test_str(self):
        r = SearchResult(
            username="u",
            filename="\\Music\\Song.flac",
            size=30_000_000,
            length=180,
            bit_depth=16,
            sample_rate=44100,
        )
        s = str(r)
        assert "Song.flac" in s
        assert "3:00" in s

    def test_quality_display_bit_depth_sample_rate_only(self):
        r = SearchResult(
            username="u",
            filename="f.flac",
            size=100,
            bit_depth=16,
            sample_rate=44100,
        )
        assert "16bit/44.1kHz" in r.quality_display
        assert "kbps" not in r.quality_display


class TestDownloadStatus:
    """Test DownloadStatus dataclass properties."""

    def test_is_complete_completed(self):
        s = DownloadStatus(username="u", filename="f", state="Completed, Succeeded")
        assert s.is_complete is True

    def test_is_complete_succeeded(self):
        s = DownloadStatus(username="u", filename="f", state="Succeeded")
        assert s.is_complete is True

    def test_is_complete_in_progress(self):
        s = DownloadStatus(username="u", filename="f", state="InProgress")
        assert s.is_complete is False

    def test_is_failed_errored(self):
        s = DownloadStatus(username="u", filename="f", state="Errored")
        assert s.is_failed is True

    def test_is_failed_rejected(self):
        s = DownloadStatus(username="u", filename="f", state="Rejected")
        assert s.is_failed is True

    def test_is_failed_timedout(self):
        s = DownloadStatus(username="u", filename="f", state="TimedOut")
        assert s.is_failed is True

    def test_is_failed_cancelled(self):
        s = DownloadStatus(username="u", filename="f", state="Cancelled")
        assert s.is_failed is True

    def test_is_failed_normal(self):
        s = DownloadStatus(username="u", filename="f", state="InProgress")
        assert s.is_failed is False

    def test_is_active_in_progress(self):
        s = DownloadStatus(username="u", filename="f", state="InProgress")
        assert s.is_active is True

    def test_is_active_complete(self):
        s = DownloadStatus(username="u", filename="f", state="Completed")
        assert s.is_active is False

    def test_is_active_failed(self):
        s = DownloadStatus(username="u", filename="f", state="Errored")
        assert s.is_active is False

    def test_is_queued_and_state_display(self):
        queued = DownloadStatus(username="u", filename="f", state="Queued, Remotely")
        assert queued.is_queued is True
        assert queued.state_display == "⌛ queued at peer"
        xfer = DownloadStatus(username="u", filename="f", state="InProgress")
        assert xfer.is_queued is False
        assert xfer.state_display == "⬇️ transferring"
