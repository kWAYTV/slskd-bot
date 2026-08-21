"""Sending audio to Telegram: document fallback, OGG conversion, previews."""

from __future__ import annotations

import contextlib
import logging
import os

from telegram.error import BadRequest

from music_downloader.catalog.track import TrackInfo
from music_downloader.soulseek.result import SearchResult
from music_downloader.telegram.download.transfer import remember_approval_message

logger = logging.getLogger(__name__)


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
        caption = (
            f"🎧 {label} OGG preview — Telegram only sends up to {file_limit // (1024 * 1024)}MB\n{quality_line}\n"
        ) + (
            (f"Save the untouched {file_size / (1024 * 1024):.0f}MB {result.extension.upper()} to the library?")
            if can_save
            else ("Sent to you — not saved to the library.")
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
        text=(
            (f"❌ {label} Could not create preview for {file_size / (1024 * 1024):.0f}MB file.\n{quality_line}\n\n")
            + (("Save to library anyway?") if can_save else ("Could not create a preview."))
        ),
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
        caption = (f"🎧 {label} ~1 min preview (full file: {file_size / (1024 * 1024):.0f}MB)\n{quality_line}\n") + (
            ("Save to library?") if can_save else ("Sent to you — not saved to the library.")
        )
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
