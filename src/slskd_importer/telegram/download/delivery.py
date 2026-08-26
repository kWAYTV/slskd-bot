"""Sending audio to Telegram: document fallback, OGG conversion, previews, artwork."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from telegram.error import BadRequest

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.library.artwork import embed_artwork_into_file, fetch_spotify_artwork
from slskd_importer.library.flac import FlacVerdict, analyze_flac
from slskd_importer.library.preview import convert_to_ogg, create_preview_clip
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.telegram.download.transfer import remember_approval_message

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


async def send_audio_or_document(
    context,
    chat_id: int,
    source_path: str,
    *,
    filename: str,
    title: str,
    performer: str,
    duration: int,
    caption: str,
    reply_markup=None,
):
    """send_audio with a send_document fallback on BadRequest. Returns the sent message."""
    try:
        with open(source_path, "rb") as f:
            return await context.bot.send_audio(
                chat_id=chat_id,
                audio=f,
                filename=filename,
                title=title,
                performer=performer,
                duration=duration,
                caption=caption,
                reply_markup=reply_markup,
            )
    except BadRequest:
        logger.info("send_audio failed, falling back to send_document for %s", filename)
        with open(source_path, "rb") as f:
            return await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=filename,
                caption=caption,
                reply_markup=reply_markup,
            )


async def send_large_file(
    self,
    context,
    chat_id: int,
    track: TrackInfo,
    result: SearchResult,
    source_path: str,
    file_size: int,
    quality_line: str,
    label: str,
    dl_id: str,
    reply_markup=None,
    can_save: bool = True,
) -> bool:
    """Convert an over-limit file to OGG and send. Trim only as last resort.

    Returns True when audio (full OGG or preview) was actually sent to the user.
    """
    ogg_path = await self._convert_to_ogg(source_path)
    if ogg_path and await _send_full_ogg(
        self, context, chat_id, track, result, ogg_path, file_size, quality_line, label, dl_id, reply_markup, can_save
    ):
        return True

    preview_path = await self._create_preview(source_path, duration_secs=60.0)
    if not preview_path:
        await _report_preview_failure(
            self, context, chat_id, source_path, file_size, quality_line, label, dl_id, reply_markup, can_save
        )
        return False

    return await _send_minute_preview(
        self, context, chat_id, track, preview_path, file_size, quality_line, label, dl_id, reply_markup, can_save
    )


async def _send_full_ogg(
    self,
    context,
    chat_id: int,
    track: TrackInfo,
    result: SearchResult,
    ogg_path: str,
    file_size: int,
    quality_line: str,
    label: str,
    dl_id: str,
    reply_markup,
    can_save: bool,
) -> bool:
    """Send the whole file as OGG if it fits the limit. Always removes the OGG."""
    file_limit = self.config.telegram_file_limit
    try:
        if os.path.getsize(ogg_path) > file_limit:
            return False

        # The OGG is only the in-chat preview: Telegram bots cannot send
        # files above the configured limit. Approval saves the original.
        caption = self.t(
            chat_id,
            "ogg_caption",
            label=label,
            limit=file_limit // (1024 * 1024),
            quality=quality_line,
        ) + (
            self.t(
                chat_id,
                "ogg_save",
                size=f"{file_size / (1024 * 1024):.0f}",
                fmt=result.extension.upper(),
            )
            if can_save
            else self.t(chat_id, "ogg_sent")
        )
        with open(ogg_path, "rb") as f:
            sent = await context.bot.send_audio(
                chat_id=chat_id,
                audio=f,
                filename=self.processor.build_filename(track.artist, track.title, "ogg"),
                title=track.title,
                performer=track.artist,
                duration=track.duration_secs,
                caption=caption,
                reply_markup=reply_markup,
            )
        remember_approval_message(self, dl_id, sent.message_id)
        return True
    finally:
        with contextlib.suppress(OSError):
            os.unlink(ogg_path)


async def _report_preview_failure(
    self,
    context,
    chat_id: int,
    source_path: str,
    file_size: int,
    quality_line: str,
    label: str,
    dl_id: str,
    reply_markup,
    can_save: bool,
) -> None:
    logger.error("Preview creation failed for %s, cannot send to Telegram", source_path)
    sent = await context.bot.send_message(
        chat_id=chat_id,
        text=self.t(
            chat_id,
            "preview_failed",
            label=label,
            size=f"{file_size / (1024 * 1024):.0f}",
            quality=quality_line,
        )
        + (self.t(chat_id, "preview_save_anyway") if can_save else self.t(chat_id, "preview_none")),
        reply_markup=reply_markup,
    )
    remember_approval_message(self, dl_id, sent.message_id)


async def _send_minute_preview(
    self,
    context,
    chat_id: int,
    track: TrackInfo,
    preview_path: str,
    file_size: int,
    quality_line: str,
    label: str,
    dl_id: str,
    reply_markup,
    can_save: bool,
) -> bool:
    """Send a ~1 minute trimmed preview. Always removes the preview file."""
    try:
        preview_ext = os.path.splitext(preview_path)[1].lstrip(".")
        caption = self.t(
            chat_id,
            "preview_caption",
            label=label,
            size=f"{file_size / (1024 * 1024):.0f}",
            quality=quality_line,
        ) + (self.t(chat_id, "preview_save") if can_save else self.t(chat_id, "ogg_sent"))
        with open(preview_path, "rb") as f:
            sent = await context.bot.send_audio(
                chat_id=chat_id,
                audio=f,
                filename=self.processor.build_filename(track.artist, f"{track.title} (1min preview)", preview_ext),
                title=f"{track.title} (1min preview)",
                performer=track.artist,
                duration=60,
                caption=caption,
                reply_markup=reply_markup,
            )
        remember_approval_message(self, dl_id, sent.message_id)
        return True
    finally:
        with contextlib.suppress(OSError):
            os.unlink(preview_path)
