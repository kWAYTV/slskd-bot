"""Parse raw slskd search responses into SearchResult objects."""

import logging

from slskd_importer.library.formats import AUDIO_EXTENSIONS
from slskd_importer.soulseek.result import SearchResult

logger = logging.getLogger(__name__)


def parse_search_responses(responses: list[dict], flac_only: bool = True) -> list[SearchResult]:
    """Extract audio files from raw slskd responses, filtering by extension locally."""
    results = []
    allowed = {"flac"} if flac_only else AUDIO_EXTENSIONS

    for response in responses:
        username = response.get("username", "")
        has_free_slot = response.get("hasFreeUploadSlot", False)
        upload_speed = response.get("uploadSpeed", 0)
        queue_length = response.get("queueLength", 0)

        for f in response.get("files", []):
            filename = f.get("filename", "")
            extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

            if extension not in allowed:
                continue

            results.append(
                SearchResult(
                    username=username,
                    filename=filename,
                    size=f.get("size", 0),
                    bit_rate=f.get("bitRate"),
                    bit_depth=f.get("bitDepth"),
                    sample_rate=f.get("sampleRate"),
                    length=f.get("length"),
                    has_free_slot=has_free_slot,
                    upload_speed=upload_speed,
                    queue_length=queue_length,
                )
            )

    label = "FLAC" if flac_only else "audio"
    logger.info(f"Parsed {len(results)} {label} results from {len(responses)} responses")
    return results
