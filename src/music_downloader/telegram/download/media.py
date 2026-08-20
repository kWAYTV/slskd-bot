"""Async wrappers around library media operations (analysis, conversion, artwork)."""

from __future__ import annotations

import asyncio
import logging

from music_downloader.catalog.track import TrackInfo
from music_downloader.library.artwork import embed_artwork_into_file, fetch_spotify_artwork
from music_downloader.library.flac import FlacVerdict, analyze_flac
from music_downloader.library.preview import convert_to_ogg, create_preview_clip

logger = logging.getLogger(__name__)


async def analyze_flac_async(filepath: str) -> FlacVerdict | None:
    """Run spectral analysis on a FLAC file in a thread to avoid blocking."""
    try:
        verdict = await asyncio.to_thread(analyze_flac, filepath)
        if verdict:
            logger.info("FLAC analysis for %s: %s (cutoff=%.1fkHz)", filepath, verdict.verdict, verdict.cutoff_khz)
        return verdict
    except Exception:
        logger.exception("FLAC analysis failed for %s", filepath)
        return None


async def convert_to_ogg_async(filepath: str) -> str | None:
    """Convert a full audio file to OGG Opus in a thread."""
    try:
        return await asyncio.to_thread(convert_to_ogg, filepath)
    except Exception:
        logger.exception("OGG conversion failed for %s", filepath)
        return None


async def create_preview_async(filepath: str, duration_secs: float = 60.0) -> str | None:
    """Create a trimmed audio preview clip in a thread to avoid blocking."""
    try:
        return await asyncio.to_thread(create_preview_clip, filepath, duration_secs)
    except Exception:
        logger.exception("Preview clip creation failed for %s", filepath)
        return None


async def embed_spotify_artwork(self, filepath: str, track: TrackInfo) -> None:
    """Fetch album artwork from Spotify and embed into the saved file."""
    try:
        art = await asyncio.to_thread(fetch_spotify_artwork, self.spotify.sp, track.artist, track.title)
        if art:
            ok = await asyncio.to_thread(embed_artwork_into_file, filepath, art)
            if ok:
                logger.info("Embedded Spotify artwork into %s (%d KB)", filepath, len(art) // 1024)
    except Exception:
        logger.debug("Artwork embedding failed for %s", filepath, exc_info=True)
