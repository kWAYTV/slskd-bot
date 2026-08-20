"""Sending audio to Telegram: document fallback, OGG conversion, previews."""

from __future__ import annotations

import contextlib
import logging
import os

from telegram.error import BadRequest

from music_downloader.catalog.track import TrackInfo
from music_downloader.i18n.catalog import gettext as _
from music_downloader.soulseek.result import SearchResult

logger = logging.getLogger(__name__)

TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024


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
    """Convert a >50 MB file to OGG and send. Trim only as last resort.

    Returns True when audio (full OGG or preview) was actually sent to the user.
    """
    ogg_path = await self._convert_to_ogg(source_path)

    if ogg_path:
        ogg_size = os.path.getsize(ogg_path)
        if ogg_size <= TELEGRAM_FILE_LIMIT:
            try:
                target_name = self.processor.build_filename(track.artist, track.title, "ogg")
                # The OGG is only the in-chat preview: Telegram bots cannot send
                # files above TELEGRAM_FILE_LIMIT. Approval saves the original.
                caption = _("🎧 {label} OGG preview — Telegram only sends up to {limit}MB\n{quality}\n").format(
                    label=label,
                    limit=TELEGRAM_FILE_LIMIT // (1024 * 1024),
                    quality=quality_line,
                ) + (
                    _("Save the untouched {size:.0f}MB {fmt} to the library?").format(
                        size=file_size / (1024 * 1024),
                        fmt=result.extension.upper(),
                    )
                    if can_save
                    else _("Sent to you — not saved to the library.")
                )
                with open(ogg_path, "rb") as f:
                    sent = await context.bot.send_audio(
                        chat_id=chat_id,
                        audio=f,
                        filename=target_name,
                        title=track.title,
                        performer=track.artist,
                        duration=track.duration_secs,
                        caption=caption,
                        reply_markup=reply_markup,
                    )
                if dl_id in self.downloads:
                    self.downloads[dl_id].approval_message_id = sent.message_id
                return True
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(ogg_path)
        else:
            with contextlib.suppress(OSError):
                os.unlink(ogg_path)

    preview_path = await self._create_preview(source_path, duration_secs=60.0)
    if not preview_path:
        logger.error("Preview creation failed for %s, cannot send to Telegram", source_path)
        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=(
                _("❌ {label} Could not create preview for {size:.0f}MB file.\n{quality}\n\n").format(
                    label=label,
                    size=file_size / (1024 * 1024),
                    quality=quality_line,
                )
                + (_("Save to library anyway?") if can_save else _("Could not create a preview."))
            ),
            reply_markup=reply_markup,
        )
        if dl_id in self.downloads:
            self.downloads[dl_id].approval_message_id = sent.message_id
        return False

    try:
        preview_ext = os.path.splitext(preview_path)[1].lstrip(".")
        target_name = self.processor.build_filename(track.artist, f"{track.title} (1min preview)", preview_ext)
        preview_caption = _("🎧 {label} ~1 min preview (full file: {size:.0f}MB)\n{quality}\n").format(
            label=label,
            size=file_size / (1024 * 1024),
            quality=quality_line,
        ) + (_("Save to library?") if can_save else _("Sent to you — not saved to the library."))
        with open(preview_path, "rb") as f:
            sent = await context.bot.send_audio(
                chat_id=chat_id,
                audio=f,
                filename=target_name,
                title=f"{track.title} (1min preview)",
                performer=track.artist,
                duration=60,
                caption=preview_caption,
                reply_markup=reply_markup,
            )
        if dl_id in self.downloads:
            self.downloads[dl_id].approval_message_id = sent.message_id
        return True
    finally:
        with contextlib.suppress(OSError):
            os.unlink(preview_path)
