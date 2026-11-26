"""OGG Opus conversion, for files over Telegram's upload limit."""

import contextlib
import logging
import os
import tempfile

logger = logging.getLogger(__name__)


def convert_to_ogg(filepath: str) -> str | None:
    """
    Convert a full audio file to OGG Opus using ffmpeg.

    Preserves the entire duration — no trimming. Caller deletes the temp file.
    """
    import subprocess

    ogg_path = None
    try:
        fd, ogg_path = tempfile.mkstemp(suffix=".ogg")
        os.close(fd)

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                filepath,
                "-c:a",
                "libopus",
                "-b:a",
                "128k",
                "-vn",
                "-map_metadata",
                "-1",
                ogg_path,
            ],
            capture_output=True,
            timeout=300,
            check=True,
        )

        ogg_size = os.path.getsize(ogg_path)
        if ogg_size == 0:
            os.unlink(ogg_path)
            return None

        logger.info(
            "Converted to OGG Opus: %s (%.1f MB)",
            ogg_path,
            ogg_size / (1024 * 1024),
        )
        return ogg_path

    except Exception:
        logger.exception("Failed to convert to OGG: %s", filepath)
        if ogg_path:
            with contextlib.suppress(OSError):
                os.unlink(ogg_path)
        return None
