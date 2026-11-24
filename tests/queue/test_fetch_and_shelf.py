"""Fetching a copy to disk, discarding one, and the library shelf."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from slskd_importer.history.store import HistoryRepository
from slskd_importer.library.files import FileProcessor
from slskd_importer.queue.fetch import discard, fetch
from slskd_importer.queue.shelf import LibraryShelf
from slskd_importer.records.database import Database
from slskd_importer.soulseek.result import DownloadStatus
from tests.queue.helpers import make_result, make_track


def status(state, transfer_id="t1"):
    return DownloadStatus("user0", "f", state, transfer_id=transfer_id)


def make_slskd(final):
    slskd = MagicMock()
    slskd.enqueue_download.return_value = True
    slskd.wait_for_download = AsyncMock(return_value=final)
    return slskd


async def test_fetch_lands_the_file():
    slskd = make_slskd(status("Completed, Succeeded"))
    processor = MagicMock()
    processor.find_downloaded_file.return_value = "/downloads/user0/x.flac"
    landed = await fetch(slskd, processor, make_result(), 5)
    assert landed.ok and landed.path == "/downloads/user0/x.flac" and landed.transfer_id == "t1"
    slskd.cancel_transfer.assert_not_called()


async def test_fetch_enqueue_refused():
    slskd = MagicMock()
    slskd.enqueue_download.return_value = False
    landed = await fetch(slskd, MagicMock(), make_result(), 5)
    assert not landed.ok and landed.error == "peer offline or refused"


@pytest.mark.parametrize(
    ("final", "error"), [(None, "timed out"), (status("Completed, Errored"), "completed, errored")]
)
async def test_fetch_failure_removes_the_transfer(final, error):
    slskd = make_slskd(final)
    landed = await fetch(slskd, MagicMock(), make_result(), 5)
    assert landed.error == error
    slskd.cancel_transfer.assert_called_once()


async def test_fetch_cancelled_removes_the_transfer():
    slskd = make_slskd(None)
    slskd.wait_for_download = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await fetch(slskd, MagicMock(), make_result(), 5)
    slskd.cancel_transfer.assert_called_once()


async def test_fetch_file_missing_on_disk():
    slskd = make_slskd(status("Completed, Succeeded"))
    processor = MagicMock()
    processor.find_downloaded_file.return_value = None
    with patch("slskd_importer.queue.fetch.LOCATE_RETRY_SECS", 0):
        landed = await fetch(slskd, processor, make_result(), 5)
    assert not landed.ok and "missing" in landed.error


async def test_discard_falls_back_to_slskd_on_read_only_mount(tmp_path):
    path = tmp_path / "user0" / "x.flac"
    path.parent.mkdir()
    path.write_bytes(b"x")
    slskd, processor = MagicMock(), MagicMock()
    processor.cleanup_download.return_value = False
    processor.relative_download_path.return_value = "user0/x.flac"
    slskd.delete_downloaded_file.return_value = True
    await discard(slskd, processor, make_result(), str(path), "t1")
    slskd.cancel_transfer.assert_called_once()
    slskd.delete_downloaded_file.assert_called_once_with("user0/x.flac")


async def test_discard_without_a_file_only_stops_the_transfer():
    slskd, processor = MagicMock(), MagicMock()
    await discard(slskd, processor, make_result(), None, None)
    slskd.cancel_transfer.assert_called_once()
    processor.cleanup_download.assert_not_called()


@pytest.fixture
def shelf(tmp_path):
    processor = FileProcessor(str(tmp_path / "downloads"), str(tmp_path / "music"))
    history = HistoryRepository(Database(str(tmp_path / "db" / "h.db")))
    spotify = MagicMock()
    with patch("slskd_importer.queue.shelf.fetch_spotify_artwork", return_value=None):
        yield LibraryShelf(processor, spotify, history), tmp_path


async def test_place_owned_and_remove(shelf):
    library, tmp_path = shelf
    source = tmp_path / "landed.flac"
    source.write_bytes(b"not really flac")
    track, result = make_track(), make_result()

    assert library.owned_as(track) is None
    placed = await library.place(track, result, str(source), chat_id=67890)
    assert placed.name == "Nancy Sinatra - Bang Bang.flac"
    assert os.path.isfile(library.path_of(placed.name))
    assert library.owned_as(track) == placed.name

    assert library.remove(placed.name, placed.history_id) is True
    assert not os.path.exists(library.path_of(placed.name))
    assert library.owned_as(track) is None  # a past save does not count once its file is gone
    assert library.remove(placed.name, placed.history_id) is False


async def test_place_fails_for_a_missing_source(shelf):
    library, tmp_path = shelf
    assert await library.place(make_track(), make_result(), str(tmp_path / "nope.flac"), 1) is None


def test_record_delivery(shelf):
    library, _ = shelf
    assert library.record(make_track(), make_result(), "delivered", 67890) > 0
