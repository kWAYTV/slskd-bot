"""Fetch one Soulseek copy to disk, and throw a fetched copy away."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from slskd_importer.library.files import FileProcessor
from slskd_importer.soulseek.client import SlskdClient
from slskd_importer.soulseek.result import DownloadStatus, SearchResult

ProgressHook = Callable[[DownloadStatus], Awaitable[None]]

# slskd marks a transfer complete a moment before it moves the file out of
# incomplete/, so the first disk lookup can miss it.
LOCATE_RETRY_SECS = 10.0
LOCATE_RETRY_STEP_SECS = 0.5
QUEUED_TOO_LONG = "stuck in the peer's queue"


@dataclass
class Landed:
    """A finished fetch: *path* on disk, or *error* saying why there is none."""

    path: str | None = None
    transfer_id: str | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.path) and not self.error


async def fetch(
    slskd: SlskdClient,
    processor: FileProcessor,
    result: SearchResult,
    timeout_secs: int,
    on_progress: ProgressHook | None = None,
    queue_patience_secs: float | None = None,
) -> Landed:
    """Enqueue on slskd, wait for the transfer, find the file. A cancelled or failed transfer is removed from slskd.

    *queue_patience_secs*: give up on a copy that sits this long in the peer's
    upload queue without starting (None waits the whole timeout).
    """
    if not await asyncio.to_thread(slskd.enqueue_download, result):
        return Landed(error="peer offline or refused")

    transfer_id: str | None = None
    queued_since: float | None = None
    out_of_patience = asyncio.Event()

    async def track(status: DownloadStatus) -> None:
        nonlocal transfer_id, queued_since
        transfer_id = status.transfer_id or transfer_id
        if not status.is_queued:
            queued_since = None
        else:
            queued_since = queued_since or time.monotonic()
            if queue_patience_secs is not None and time.monotonic() - queued_since >= queue_patience_secs:
                out_of_patience.set()
        if on_progress is not None:
            await on_progress(status)

    transfer = asyncio.ensure_future(
        slskd.wait_for_download(result.username, result.filename, timeout_secs=timeout_secs, progress_callback=track)
    )
    patience = asyncio.ensure_future(out_of_patience.wait())
    try:
        await asyncio.wait({transfer, patience}, return_when=asyncio.FIRST_COMPLETED)
    except BaseException:
        transfer.cancel()
        await _stop_transfer(slskd, result, transfer_id)
        raise
    finally:
        patience.cancel()
    if not transfer.done():
        transfer.cancel()
        await _stop_transfer(slskd, result, transfer_id)
        return Landed(error=QUEUED_TOO_LONG)
    try:
        status = transfer.result()
    except BaseException:
        await _stop_transfer(slskd, result, transfer_id)
        raise
    # slskd reports failures as "Completed, Errored": check is_failed, not is_complete.
    if status is None or status.is_failed:
        await _stop_transfer(slskd, result, status.transfer_id if status else transfer_id)
        return Landed(error=status.state.lower() if status else "timed out")

    path = await _locate(processor, result)
    if path is None:
        return Landed(transfer_id=status.transfer_id, error="file missing on disk (check DOWNLOAD_DIR)")
    return Landed(path=path, transfer_id=status.transfer_id)


async def discard(
    slskd: SlskdClient,
    processor: FileProcessor,
    result: SearchResult,
    path: str | None,
    transfer_id: str | None,
) -> None:
    """Remove a fetched copy: the slskd transfer row and the file.

    When DOWNLOAD_DIR is mounted read-only the local delete fails and slskd is
    asked to delete the file itself (needs SLSKD_REMOTE_FILE_MANAGEMENT=true).
    """
    await _stop_transfer(slskd, result, transfer_id)
    if not path or not os.path.isfile(path):
        return
    if await asyncio.to_thread(processor.cleanup_download, path):
        return
    relative = await asyncio.to_thread(processor.relative_download_path, path)
    if relative and await asyncio.to_thread(slskd.delete_downloaded_file, relative):
        parent = relative.rsplit("/", 1)[0] if "/" in relative else ""
        if parent and not os.listdir(os.path.dirname(path)):
            await asyncio.to_thread(slskd.delete_downloaded_directory, parent)


async def _stop_transfer(slskd: SlskdClient, result: SearchResult, transfer_id: str | None) -> None:
    await asyncio.to_thread(slskd.cancel_transfer, result.username, result.filename, transfer_id)


async def _locate(processor: FileProcessor, result: SearchResult) -> str | None:
    waited = 0.0
    while True:
        path = await asyncio.to_thread(processor.find_downloaded_file, result.username, result.filename)
        if path is not None or waited >= LOCATE_RETRY_SECS:
            return path
        await asyncio.sleep(LOCATE_RETRY_STEP_SECS)
        waited += LOCATE_RETRY_STEP_SECS
