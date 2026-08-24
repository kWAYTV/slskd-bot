"""slskd remote file management: list and delete downloaded files."""

import logging

logger = logging.getLogger(__name__)


def delete_downloaded_file(api, relative_path: str) -> bool:
    """Delete a file inside slskd's downloads directory via remote file management.

    ``relative_path`` is relative to the slskd downloads directory (e.g.
    ``username/song.flac``).  Requires ``remoteFileManagement: true`` in the
    slskd configuration.
    """
    try:
        ok = api.files.delete_downloaded_file(relative_path)
        if not ok:
            logger.warning(f"slskd refused to delete downloaded file: {relative_path}")
            return False
        logger.info(f"Deleted downloaded file via slskd: {relative_path}")
        return True
    except Exception:
        logger.exception(f"Failed to delete downloaded file via slskd: {relative_path}")
        return False


def delete_downloaded_directory(api, relative_dir: str) -> bool:
    """Delete a subdirectory inside slskd's downloads directory via remote file management."""
    try:
        ok = api.files.delete_downloaded_directory(relative_dir)
        if ok:
            logger.info(f"Deleted downloaded directory via slskd: {relative_dir}")
        return bool(ok)
    except Exception:
        logger.debug(f"Failed to delete downloaded directory via slskd: {relative_dir}", exc_info=True)
        return False
