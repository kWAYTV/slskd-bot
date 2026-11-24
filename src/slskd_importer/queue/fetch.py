"""Fetch one Soulseek copy to disk, and throw a fetched copy away."""

from __future__ import annotations

import asyncio
import os
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
) -> Landed:
    """Enqueue on slskd, wait for the transfer, find the file. A cancelled or failed transfer is removed from slskd."""
    if not await asyncio.to_thread(slskd.enqueue_download, result):
        return Landed(error="peer offline or refused")

    transfer_id: str | None = None

    async def track(status: DownloadStatus) -> None:
        nonlocal transfer_id
        transfer_id = status.transfer_id or transfer_id
        if on_progress is not None:
            await on_progress(status)

    try:
        status = await slskd.wait_for_download(
            result.username, result.filename, timeout_secs=timeout_secs, progress_callback=track
        )
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
