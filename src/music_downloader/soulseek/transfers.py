"""slskd download transfers: enqueue, status, completion wait, cancellation."""

import asyncio
import logging
import time
from collections.abc import Callable

from music_downloader.soulseek.result import DownloadStatus, SearchResult

logger = logging.getLogger(__name__)

StatusGetter = Callable[[str, str], DownloadStatus | None]


def enqueue(api, result: SearchResult) -> bool:
    """Enqueue a file for download via slskd."""
    try:
        files = [{"filename": result.filename, "size": result.size}]
        api.transfers.enqueue(username=result.username, files=files)
        logger.info(f"Enqueued download: {result.basename} from {result.username}")
        return True
    except Exception:
        logger.exception(f"Failed to enqueue download: {result.basename}")
        return False


def get_status(api, username: str, filename: str) -> DownloadStatus | None:
    """Get the download status for a specific file."""
    try:
        downloads = api.transfers.get_downloads(username=username)

        if not downloads:
            return None

        for directory in downloads.get("directories", []):
            for transfer in directory.get("files", []):
                if transfer.get("filename") == filename:
                    return DownloadStatus(
                        username=username,
                        filename=filename,
                        state=transfer.get("state", "Unknown"),
                        percent_complete=transfer.get("percentComplete", 0),
                        bytes_transferred=transfer.get("bytesTransferred", 0),
                        size=transfer.get("size", 0),
                        average_speed=transfer.get("averageSpeed", 0),
                        transfer_id=str(transfer["id"]) if transfer.get("id") is not None else None,
                    )

        return None

    except Exception:
        logger.exception(f"Failed to get download status for {filename}")
        return None


async def wait_for_completion(
    status_getter: StatusGetter,
    username: str,
    filename: str,
    timeout_secs: int = 600,
    progress_callback=None,
) -> DownloadStatus | None:
    """Wait for a download to complete, polling periodically.

    ``progress_callback`` is an optional async callable invoked with the
    in-flight ``DownloadStatus`` on each poll (not on completion/failure).
    Callback errors are logged and never abort the wait.
    """
    start = time.time()

    while time.time() - start < timeout_secs:
        await asyncio.sleep(3)
        status = await asyncio.to_thread(status_getter, username, filename)

        if status is None:
            logger.debug(f"No status yet for {filename}")
            continue

        if status.is_complete:
            logger.info(f"Download complete: {filename}")
            return status

        if status.is_failed:
            logger.warning(f"Download failed ({status.state}): {filename}")
            return status

        logger.debug(f"Download {status.percent_complete:.0f}%: {filename}")
        if progress_callback is not None:
            try:
                await progress_callback(status)
            except Exception:
                logger.debug("Progress callback failed for %s", filename, exc_info=True)

    logger.warning(f"Download timed out after {timeout_secs}s: {filename}")
    return None


def cancel(
    api,
    status_getter: StatusGetter,
    username: str,
    filename: str,
    transfer_id: str | None = None,
) -> bool:
    """Cancel an in-flight slskd download and remove it from the transfer list."""
    try:
        tid = transfer_id
        if not tid:
            status = status_getter(username, filename)
            tid = status.transfer_id if status else None
        if not tid:
            logger.warning("No slskd transfer id to cancel for %s / %s", username, filename)
            return False
        api.transfers.cancel_download(username=username, id=tid, remove=True)
        logger.info("Cancelled slskd transfer %s (%s from %s)", tid, filename, username)
        return True
    except Exception:
        logger.exception("Failed to cancel slskd transfer for %s", filename)
        return False
