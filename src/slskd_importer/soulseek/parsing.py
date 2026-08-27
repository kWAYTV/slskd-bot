"""Parse raw slskd search responses into SearchResult objects."""

import logging

from slskd_importer.library.formats import AUDIO_EXTENSIONS, PREFERRED_EXTENSIONS
from slskd_importer.soulseek.result import SearchResult

logger = logging.getLogger(__name__)


def parse_search_responses(
    responses: list[dict],
    extensions: set[str] | frozenset[str] | None = None,
) -> list[SearchResult]:
    """Extract audio files from raw slskd responses, filtering by extension locally."""
    allowed = AUDIO_EXTENSIONS if extensions is None else extensions
    results = []

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

    label = "preferred" if allowed is PREFERRED_EXTENSIONS or allowed == PREFERRED_EXTENSIONS else "audio"
    logger.info(f"Parsed {len(results)} {label} results from {len(responses)} responses")
    return results
