"""Telegram preview helpers: full OGG conversion and trimmed clips."""

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


def create_preview_clip(filepath: str, duration_secs: float = 60.0) -> str | None:
    """
    Extract a trimmed OGG Opus clip from any audio file using ffmpeg.

    Starts at 20% into the track and takes *duration_secs* of audio.
    Caller deletes the temp file.
    """
    import json
    import subprocess

    preview_path = None
    try:
        total_duration = 0.0
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                filepath,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if probe.returncode == 0:
            fmt = json.loads(probe.stdout).get("format", {})
            total_duration = float(fmt.get("duration", 0))

        start_secs = total_duration * 0.2 if total_duration > 0 else 0

        fd, preview_path = tempfile.mkstemp(suffix=".ogg")
        os.close(fd)

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{start_secs:.2f}",
                "-i",
                filepath,
                "-t",
                f"{duration_secs:.2f}",
                "-c:a",
                "libopus",
                "-b:a",
                "128k",
                "-vn",
                "-map_metadata",
                "-1",
                preview_path,
            ],
            capture_output=True,
            timeout=120,
            check=True,
        )

        preview_size = os.path.getsize(preview_path)
        if preview_size == 0:
            os.unlink(preview_path)
            return None

        logger.info(
            "Created %ds preview clip: %s (%.1f MB)",
            duration_secs,
            preview_path,
            preview_size / (1024 * 1024),
        )
        return preview_path

    except Exception:
        logger.exception("Failed to create preview clip for: %s", filepath)
        if preview_path:
            with contextlib.suppress(OSError):
                os.unlink(preview_path)
        return None
