"""Shared slskd transfer pipeline used by manual downloads and playlist imports."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from music_downloader.soulseek.result import DownloadStatus, SearchResult
from music_downloader.telegram.core.session import PendingDownload

PROGRESS_EDIT_STEP_PCT = 10.0


@dataclass
class TransferOutcome:
    """Result of enqueue -> wait -> locate-on-disk for one slskd transfer."""

    enqueued: bool
    status: DownloadStatus | None = None
    source_path: str | None = None

    @property
    def failed(self) -> bool:
        return self.status is None or self.status.is_failed


def make_progress_callback(
    pending_dl: PendingDownload,
    render: Callable[[float], Awaitable[None]],
    min_step: float = PROGRESS_EDIT_STEP_PCT,
):
    """Build a throttled slskd progress callback.

    Records progress/transfer id on the pending download for /status and
    /cancel, and re-renders the status message only every ``min_step`` percent.
    """
    last_edited_pct = -100.0

    async def _on_progress(progress) -> None:
        nonlocal last_edited_pct
        pct = progress.percent_complete
        pending_dl.progress_percent = pct
        pending_dl.transfer_id = progress.transfer_id or pending_dl.transfer_id
        if pct - last_edited_pct < min_step:
            return
        last_edited_pct = pct
        await render(pct)

    return _on_progress


async def fetch_from_peer(self, result: SearchResult, progress_callback) -> TransferOutcome:
    """Enqueue on slskd, wait for completion, and locate the file on disk."""
    success = await asyncio.to_thread(self.slskd.enqueue_download, result)
    if not success:
        return TransferOutcome(enqueued=False)

    status = await self.slskd.wait_for_download(
        username=result.username,
        filename=result.filename,
        timeout_secs=self.config.download_timeout_secs,
        progress_callback=progress_callback,
    )
    if status is None or status.is_failed:
        return TransferOutcome(enqueued=True, status=status)

    source_path = self.processor.find_downloaded_file(result.username, result.filename)
    return TransferOutcome(enqueued=True, status=status, source_path=source_path)
