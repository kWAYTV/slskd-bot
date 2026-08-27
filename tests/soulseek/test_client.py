"""Tests for the slskd API façade."""

from unittest.mock import MagicMock, patch

import pytest

from slskd_importer.soulseek.client import SlskdClient
from slskd_importer.soulseek.parsing import parse_search_responses
from slskd_importer.soulseek.result import DownloadStatus, SearchResult


class TestParseSearchResponses:
    """Test parsing raw slskd responses into SearchResult objects."""

    def test_parse_preferred_only(self):
        responses = [
            {
                "username": "user1",
                "hasFreeUploadSlot": True,
                "uploadSpeed": 5_000_000,
                "queueLength": 0,
                "files": [
                    {
                        "filename": "\\Music\\Song.flac",
                        "size": 30_000_000,
                        "length": 180,
                        "bitDepth": 16,
                        "sampleRate": 44100,
                    },
                    {"filename": "\\Music\\Song.wav", "size": 40_000_000, "length": 180},
                    {"filename": "\\Music\\Song.mp3", "size": 10_000_000, "length": 180, "bitRate": 320},
                ],
            }
        ]
        from slskd_importer.library.formats import PREFERRED_EXTENSIONS

        results = parse_search_responses(responses, extensions=PREFERRED_EXTENSIONS)
        assert {r.extension for r in results} == {"flac", "wav"}

    def test_parse_all_audio(self):
        responses = [
            {
                "username": "user1",
                "hasFreeUploadSlot": False,
                "uploadSpeed": 1_000_000,
                "queueLength": 2,
                "files": [
                    {"filename": "\\Music\\Song.flac", "size": 30_000_000},
                    {"filename": "\\Music\\Song.mp3", "size": 10_000_000},
                    {"filename": "\\Music\\Song.ogg", "size": 8_000_000},
                    {"filename": "\\Music\\cover.jpg", "size": 500_000},
                ],
            }
        ]
        results = parse_search_responses(responses)
        assert len(results) == 3
        exts = {r.extension for r in results}
        assert "jpg" not in exts

    def test_parse_empty_responses(self):
        assert parse_search_responses([]) == []

    def test_parse_preserves_user_info(self):
        responses = [
            {
                "username": "cooluser",
                "hasFreeUploadSlot": True,
                "uploadSpeed": 9_000_000,
                "queueLength": 3,
                "files": [
                    {"filename": "\\Song.flac", "size": 100},
                ],
            }
        ]
        results = parse_search_responses(responses)
        assert results[0].username == "cooluser"
        assert results[0].has_free_slot is True
        assert results[0].upload_speed == 9_000_000
        assert results[0].queue_length == 3

    def test_parse_missing_fields(self):
        responses = [
            {
                "username": "u",
                "files": [{"filename": "\\Song.flac", "size": 0}],
            }
        ]
        results = parse_search_responses(responses)
        assert len(results) == 1
        assert results[0].has_free_slot is False
        assert results[0].upload_speed == 0


class TestSlskdClientEnqueue:
    """Test SlskdClient.enqueue_download."""

    @pytest.fixture
    def client(self):
        with patch("slskd_api.SlskdClient") as mock_cls:
            c = SlskdClient("http://localhost:5030", "test-key")
            c.client = mock_cls.return_value
            return c

    def test_enqueue_success(self, client):
        result = SearchResult(
            username="user1",
            filename="\\Music\\Song.flac",
            size=30_000_000,
        )
        client.client.transfers.enqueue = MagicMock()
        assert client.enqueue_download(result) is True
        client.client.transfers.enqueue.assert_called_once()

    def test_enqueue_failure(self, client):
        result = SearchResult(
            username="user1",
            filename="\\Music\\Song.flac",
            size=30_000_000,
        )
        client.client.transfers.enqueue = MagicMock(side_effect=Exception("Connection error"))
        assert client.enqueue_download(result) is False


class TestSlskdClientGetDownloadStatus:
    """Test SlskdClient.get_download_status."""

    @pytest.fixture
    def client(self):
        with patch("slskd_api.SlskdClient") as mock_cls:
            c = SlskdClient("http://localhost:5030", "test-key")
            c.client = mock_cls.return_value
            return c

    def test_status_found(self, client):
        client.client.transfers.get_downloads = MagicMock(
            return_value={
                "directories": [
                    {
                        "files": [
                            {
                                "filename": "\\Music\\Song.flac",
                                "state": "Completed, Succeeded",
                                "percentComplete": 100,
                                "bytesTransferred": 30_000_000,
                                "size": 30_000_000,
                                "averageSpeed": 5_000_000,
                            }
                        ]
                    }
                ]
            }
        )
        status = client.get_download_status("user1", "\\Music\\Song.flac")
        assert status is not None
        assert status.is_complete is True
        assert status.percent_complete == 100

    def test_status_not_found(self, client):
        client.client.transfers.get_downloads = MagicMock(return_value={"directories": [{"files": []}]})
        status = client.get_download_status("user1", "\\Music\\Song.flac")
        assert status is None

    def test_status_no_downloads(self, client):
        client.client.transfers.get_downloads = MagicMock(return_value=None)
        status = client.get_download_status("user1", "\\Music\\Song.flac")
        assert status is None

    def test_status_exception(self, client):
        client.client.transfers.get_downloads = MagicMock(side_effect=Exception("err"))
        status = client.get_download_status("user1", "\\Music\\Song.flac")
        assert status is None

    def test_status_includes_transfer_id(self, client):
        client.client.transfers.get_downloads = MagicMock(
            return_value={
                "directories": [
                    {
                        "files": [
                            {
                                "id": "xfer-9",
                                "filename": "\\Music\\Song.flac",
                                "state": "InProgress",
                                "percentComplete": 10,
                                "bytesTransferred": 1,
                                "size": 10,
                                "averageSpeed": 1,
                            }
                        ]
                    }
                ]
            }
        )
        status = client.get_download_status("user1", "\\Music\\Song.flac")
        assert status is not None
        assert status.transfer_id == "xfer-9"


class TestSlskdClientCancelAndPing:
    @pytest.fixture
    def client(self):
        with patch("slskd_api.SlskdClient") as mock_cls:
            c = SlskdClient("http://localhost:5030", "test-key")
            c.client = mock_cls.return_value
            return c

    def test_cancel_transfer_with_id(self, client):
        client.client.transfers.cancel_download = MagicMock()
        assert client.cancel_transfer("user1", "\\Music\\Song.flac", transfer_id="abc") is True
        client.client.transfers.cancel_download.assert_called_once_with(username="user1", id="abc", remove=True)

    def test_cancel_transfer_looks_up_status(self, client):
        client.get_download_status = MagicMock(
            return_value=DownloadStatus(username="u", filename="f", state="InProgress", transfer_id="looked-up")
        )
        client.client.transfers.cancel_download = MagicMock()
        assert client.cancel_transfer("user1", "\\Music\\Song.flac") is True
        client.client.transfers.cancel_download.assert_called_once_with(username="user1", id="looked-up", remove=True)

    def test_cancel_transfer_missing_id(self, client):
        client.get_download_status = MagicMock(return_value=None)
        assert client.cancel_transfer("user1", "\\Music\\Song.flac") is False

    def test_cancel_transfer_exception(self, client):
        client.client.transfers.cancel_download = MagicMock(side_effect=Exception("boom"))
        assert client.cancel_transfer("user1", "f", transfer_id="x") is False

    def test_ping_ok(self, client):
        client.client.application.state = MagicMock(return_value={"state": "Connected"})
        assert client.ping() is True

    def test_ping_fail(self, client):
        client.client.application.state = MagicMock(side_effect=Exception("down"))
        assert client.ping() is False


class TestSlskdClientSearch:
    """Test SlskdClient.search async method."""

    @pytest.fixture
    def client(self):
        with patch("slskd_api.SlskdClient") as mock_cls:
            c = SlskdClient("http://localhost:5030", "test-key")
            c.client = mock_cls.return_value
            return c

    @pytest.mark.asyncio
    async def test_search_exception_returns_empty(self, client):
        """search() should return empty list on exception."""
        client.client.searches.get_all = MagicMock(side_effect=Exception("fail"))
        client.client.searches.search_text = MagicMock(side_effect=Exception("fail"))
        results = await client.search("test query", timeout_secs=2)
        assert results == []

    @pytest.mark.asyncio
    async def test_search_hard_timeout_collects_partial(self, client):
        """Hard timeout should stop this call's own search and return partial results."""
        from unittest.mock import AsyncMock

        async def fake_inner(query, timeout_secs, response_limit, search_id_holder):
            search_id_holder.append("search-123")
            raise TimeoutError()

        client.searches._poll = fake_inner
        client.searches._stop_and_collect = AsyncMock(return_value=[{"username": "u"}])
        results = await client.search("query", timeout_secs=1)

        client.searches._stop_and_collect.assert_awaited_once_with("search-123")
        assert results == [{"username": "u"}]

    @pytest.mark.asyncio
    async def test_search_hard_timeout_without_id_returns_empty(self, client):
        async def fake_inner(query, timeout_secs, response_limit, search_id_holder):
            raise TimeoutError()

        client.searches._poll = fake_inner
        results = await client.search("query", timeout_secs=1)

        assert results == []


class TestSlskdClientDeleteDownloadedFile:
    """Test SlskdClient remote file management deletion."""

    @pytest.fixture
    def client(self):
        with patch("slskd_api.SlskdClient") as mock_cls:
            c = SlskdClient("http://localhost:5030", "test-key")
            c.client = mock_cls.return_value
            return c

    def test_delete_file_success(self, client):
        client.client.files.delete_downloaded_file = MagicMock(return_value=True)
        assert client.delete_downloaded_file("user/song.flac") is True
        client.client.files.delete_downloaded_file.assert_called_once_with("user/song.flac")

    def test_delete_file_refused(self, client):
        client.client.files.delete_downloaded_file = MagicMock(return_value=False)
        assert client.delete_downloaded_file("user/song.flac") is False

    def test_delete_file_exception(self, client):
        client.client.files.delete_downloaded_file = MagicMock(side_effect=Exception("403"))
        assert client.delete_downloaded_file("user/song.flac") is False

    def test_delete_directory_success(self, client):
        client.client.files.delete_downloaded_directory = MagicMock(return_value=True)
        assert client.delete_downloaded_directory("user") is True
        client.client.files.delete_downloaded_directory.assert_called_once_with("user")

    def test_delete_directory_exception(self, client):
        client.client.files.delete_downloaded_directory = MagicMock(side_effect=Exception("boom"))
        assert client.delete_downloaded_directory("user") is False


class TestSlskdClientWaitForDownload:
    """Test SlskdClient.wait_for_download async method."""

    @pytest.fixture
    def client(self):
        with patch("slskd_api.SlskdClient") as mock_cls:
            c = SlskdClient("http://localhost:5030", "test-key")
            c.client = mock_cls.return_value
            return c

    @pytest.mark.asyncio
    async def test_wait_completes(self, client):
        """wait_for_download returns completed status."""
        completed = DownloadStatus(
            username="u",
            filename="f.flac",
            state="Completed, Succeeded",
            percent_complete=100,
            bytes_transferred=100,
            size=100,
        )
        call_count = 0

        def mock_get_status(username, filename):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                return completed
            return DownloadStatus(username="u", filename="f.flac", state="InProgress", percent_complete=50)

        client.get_download_status = mock_get_status
        result = await client.wait_for_download("u", "f.flac", timeout_secs=10)
        assert result is not None
        assert result.is_complete

    @pytest.mark.asyncio
    async def test_wait_fails(self, client):
        """wait_for_download returns failed status."""
        failed = DownloadStatus(username="u", filename="f.flac", state="Errored")
        client.get_download_status = MagicMock(return_value=failed)
        result = await client.wait_for_download("u", "f.flac", timeout_secs=10)
        assert result is not None
        assert result.is_failed

    @pytest.mark.asyncio
    async def test_wait_timeout(self, client):
        """wait_for_download returns None on timeout."""
        in_progress = DownloadStatus(username="u", filename="f.flac", state="InProgress")
        client.get_download_status = MagicMock(return_value=in_progress)
        result = await client.wait_for_download("u", "f.flac", timeout_secs=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_progress_callback_invoked_in_flight_only(self, client):
        """progress_callback fires for in-flight polls, not for the terminal status."""
        call_count = 0
        completed = DownloadStatus(username="u", filename="f.flac", state="Completed, Succeeded", percent_complete=100)

        def mock_status(username, filename):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                return completed
            return DownloadStatus(username="u", filename="f.flac", state="InProgress", percent_complete=call_count * 25)

        client.get_download_status = mock_status
        seen: list[float] = []

        async def on_progress(status):
            seen.append(status.percent_complete)

        result = await client.wait_for_download("u", "f.flac", timeout_secs=30, progress_callback=on_progress)
        assert result is not None
        assert result.is_complete
        assert seen == [25, 50]

    @pytest.mark.asyncio
    async def test_progress_callback_error_does_not_abort(self, client):
        """A crashing progress_callback is swallowed and the wait continues."""
        call_count = 0
        completed = DownloadStatus(username="u", filename="f.flac", state="Completed, Succeeded")

        def mock_status(username, filename):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                return completed
            return DownloadStatus(username="u", filename="f.flac", state="InProgress", percent_complete=10)

        client.get_download_status = mock_status

        async def bad_callback(status):
            raise RuntimeError("boom")

        result = await client.wait_for_download("u", "f.flac", timeout_secs=30, progress_callback=bad_callback)
        assert result is not None
        assert result.is_complete

    @pytest.mark.asyncio
    async def test_wait_no_status_yet(self, client):
        """wait_for_download handles None status during polling."""
        call_count = 0
        completed = DownloadStatus(username="u", filename="f.flac", state="Completed")

        def mock_status(username, filename):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return None
            return completed

        client.get_download_status = mock_status
        result = await client.wait_for_download("u", "f.flac", timeout_secs=15)
        assert result is not None
        assert result.is_complete
