"""Cancellation and download artifact cleanup.

Functions take the ``MusicBot`` instance as ``self`` and are bound as class
attributes in ``core.app``.
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)


async def cancel_chat_operations(self, chat_id: int) -> bool:
    had_work, stale = self._session.cancel_chat_operations(chat_id)
    if had_work:
        logger.info("Cancelled in-flight work for chat %s (%d download(s))", chat_id, len(stale))
    for dl in stale:
        await self._cleanup_download_artifacts(dl)
    return had_work


async def cleanup_download_artifacts(self, dl) -> None:
    """Cancel the slskd transfer and delete any local file for a pending download."""
    result = dl.result
    try:
        await asyncio.to_thread(
            self.slskd.cancel_transfer,
            result.username,
            result.filename,
            dl.transfer_id,
        )
    except Exception:
        logger.debug("slskd transfer cancel failed for %s", result.basename, exc_info=True)
    await self._remove_download_file(dl.source_path)


async def remove_download_file(self, source_path: str | None) -> None:
    """Delete a downloaded file, falling back to slskd remote file management.

    When DOWNLOAD_DIR is mounted read-only the local delete fails and the
    original file would linger next to the renamed library copy.  In that
    case ask slskd (which owns the directory) to delete it instead —
    requires SLSKD_REMOTE_FILE_MANAGEMENT=true on the slskd side.
    """
    if not source_path:
        return
    if self.processor.cleanup_download(source_path) or not os.path.isfile(source_path):
        return

    rel_path = self.processor.relative_download_path(source_path)
    if not rel_path:
        logger.warning("Download outside DOWNLOAD_DIR, cannot delete via slskd: %s", source_path)
        return

    deleted = await asyncio.to_thread(self.slskd.delete_downloaded_file, rel_path)
    if not deleted:
        logger.warning(
            "Could not delete download %s locally or via slskd; the original file will remain. "
            "Mount DOWNLOAD_DIR read-write or enable remote file management on slskd "
            "(SLSKD_REMOTE_FILE_MANAGEMENT=true).",
            source_path,
        )
        return

    # Mirror local cleanup: drop the now-empty per-user directory.
    parent = os.path.dirname(source_path)
    rel_parent = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
    if rel_parent and os.path.isdir(parent) and not os.listdir(parent):
        await asyncio.to_thread(self.slskd.delete_downloaded_directory, rel_parent)
