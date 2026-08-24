"""Shared slskd transfer pipeline used by manual downloads and playlist imports."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.soulseek.result import DownloadStatus, SearchResult
from slskd_importer.telegram.core.session import PendingDownload

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
    last_state = ""

    async def _on_progress(progress) -> None:
        nonlocal last_edited_pct, last_state
        pct = progress.percent_complete
        pending_dl.progress_percent = pct
        pending_dl.transfer_id = progress.transfer_id or pending_dl.transfer_id
        pending_dl.transfer_state = progress.state
        state_changed = progress.state != last_state
        last_state = progress.state
        if not state_changed and pct - last_edited_pct < min_step:
            return
        last_edited_pct = pct
        await render(pct)

    return _on_progress


def remember_approval_message(self, dl_id: str, message_id: int) -> None:
    """Attach the approval message to the pending download, if it still exists."""
    pending_dl = self.downloads.get(dl_id)
    if pending_dl:
        pending_dl.approval_message_id = message_id


async def abort_transfer(self, dl_id: str, result: SearchResult, transfer_id: str | None = None) -> None:
    """On task cancellation: clean local artifacts, or cancel the slskd transfer."""
    pending_dl = self.downloads.pop(dl_id, None)
    if pending_dl:
        await self._cleanup_download_artifacts(pending_dl)
        return
    await asyncio.to_thread(self.slskd.cancel_transfer, result.username, result.filename, transfer_id)


async def fetch_from_peer(self, result: SearchResult, progress_callback) -> TransferOutcome:
    """Enqueue on slskd, wait for completion, and locate the file on disk."""
    async with self._download_sem:
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


async def add_history(self, track: TrackInfo, result: SearchResult, status: str, chat_id: int | None = None):
    """Record a download outcome in the history store."""
    await asyncio.to_thread(
        self.history_repo.add,
        artist=track.artist,
        title=track.title,
        album=track.album,
        filename=f"{track.artist} - {track.title}.{result.extension}",
        source_user=result.username,
        remote_path=result.filename,
        status=status,
        duration_secs=track.duration_secs,
        file_size=result.size,
        chat_id=chat_id,
        spotify_url=track.spotify_url,
    )
