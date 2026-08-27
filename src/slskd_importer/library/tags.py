"""Write catalog identity tags and drop exact-duplicate Vorbis comments."""

from __future__ import annotations

import logging
import os

import mutagen.flac

logger = logging.getLogger(__name__)


def write_canonical_tags(filepath: str, artist: str, title: str, album: str, year: str) -> None:
    """Overwrite identity tags with catalog metadata. Leaves other tags alone."""
    # process_file writes to ``*.flac.importing`` first; ignore that suffix.
    name = filepath.removesuffix(".importing")
    ext = os.path.splitext(name)[1].lower()
    try:
        if ext == ".flac":
            audio = mutagen.flac.FLAC(filepath)
            audio["artist"] = [artist]
            audio["title"] = [title]
            if album:
                audio["album"] = [album]
            if year:
                audio["date"] = [year]
            audio.save()
            return
        if ext in {".m4a", ".mp4", ".alac", ".aac"}:
            from mutagen.mp4 import MP4

            audio = MP4(filepath)
            audio["\xa9ART"] = [artist]
            audio["\xa9nam"] = [title]
            if album:
                audio["\xa9alb"] = [album]
            if year:
                audio["\xa9day"] = [year]
            audio.save()
            return
        if ext == ".mp3":
            from mutagen.id3 import ID3, TALB, TDRC, TIT2, TPE1, ID3NoHeaderError

            try:
                tags = ID3(filepath)
            except ID3NoHeaderError:
                tags = ID3()
            tags["TPE1"] = TPE1(encoding=3, text=[artist])
            tags["TIT2"] = TIT2(encoding=3, text=[title])
            if album:
                tags["TALB"] = TALB(encoding=3, text=[album])
            if year:
                tags["TDRC"] = TDRC(encoding=3, text=[year])
            tags.save(filepath)
    except Exception:
        logger.debug("Canonical tag write failed for %s", filepath, exc_info=True)


def dedup_flac_tags(filepath: str) -> None:
    """Remove exact duplicate Vorbis comment values in a FLAC file."""
    try:
        audio = mutagen.flac.FLAC(filepath)
        changed = False
        for key in list(audio.keys()):
            values = audio.get(key, [])
            deduped = list(dict.fromkeys(values))
            if len(deduped) == len(values):
                continue
            audio[key] = deduped
            changed = True
        if changed:
            audio.save()
            logger.info("Deduplicated FLAC tags: %s", os.path.basename(filepath))
    except Exception:
        logger.debug("Tag dedup failed for %s", filepath, exc_info=True)
