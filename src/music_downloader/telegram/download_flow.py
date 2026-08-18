"""Download, preview, approval, and retry conversation."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from music_downloader.catalog.track import TrackInfo
from music_downloader.library.artwork import embed_artwork_into_file, fetch_spotify_artwork
from music_downloader.library.flac import FlacVerdict, analyze_flac
from music_downloader.library.preview import convert_to_ogg, create_preview_clip
from music_downloader.soulseek.result import SearchResult
from music_downloader.telegram.keyboards import (
    build_approve_keyboard,
    build_retry_keyboard,
    build_retry_next_keyboard,
)
from music_downloader.telegram.messages import escape_md, safe_query_edit
from music_downloader.telegram.session import PendingDownload

logger = logging.getLogger(__name__)

TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024


async def handle_download_selection(self, update, context, chat_id: int, data: str):
    """Handle when user picks a file to download from results."""
    query = update.callback_query
    pending = self.pending.get(chat_id)
    if not pending:
        await query.edit_message_text("Search expired. Send a new query.")
        return

    action = data.split(":", 1)[1]

    if action == "cancel":
        del self.pending[chat_id]
        await query.edit_message_text("Cancelled.")
        return

    if action == "auto":
        index = 0
    else:
        try:
            index = int(action)
        except ValueError:
            return

    if index >= len(pending.results):
        return

    result = pending.results[index]
    track = pending.track

    with contextlib.suppress(BadRequest):
        await query.edit_message_reply_markup(reply_markup=None)

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"⬇️ *Downloading #{index + 1}...*\n"
            f"{escape_md(track.artist)} - {escape_md(track.title)}\n"
            f"From: `{result.username}`\n"
            f"File: `{result.basename}`"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )

    task = context.application.create_task(
        self._do_download(context, chat_id, track, result, status_msg, index),
        update=update,
    )
    self._track_task(chat_id, task)


def has_next_result(self, chat_id: int, current_index: int) -> bool:
    pending = self.pending.get(chat_id)
    return pending is not None and current_index + 1 < len(pending.results)


async def do_download(
    self, context, chat_id: int, track: TrackInfo, result: SearchResult, status_msg, result_index: int = 0
):
    """Download a file, send it to Telegram for preview, and ask for approval."""
    dl_id = self._next_dl_id()
    label = f"#{result_index + 1}"

    try:
        success = await asyncio.to_thread(self.slskd.enqueue_download, result)
        if not success:
            pending_dl = PendingDownload(
                track=track,
                result=result,
                chat_id=chat_id,
                status_message_id=status_msg.message_id,
                result_index=result_index,
            )
            self.downloads[dl_id] = pending_dl
            has_next = self._has_next_result(chat_id, result_index)
            await status_msg.edit_text(
                f"❌ Failed to enqueue download from `{result.username}`.\nThe user might be offline.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_retry_next_keyboard(dl_id) if has_next else build_retry_keyboard(dl_id),
            )
            return

        status = await self.slskd.wait_for_download(
            username=result.username,
            filename=result.filename,
            timeout_secs=self.config.download_timeout_secs,
        )

        if status is None or status.is_failed:
            state = status.state if status else "Timeout"
            pending_dl = PendingDownload(
                track=track,
                result=result,
                chat_id=chat_id,
                status_message_id=status_msg.message_id,
                result_index=result_index,
            )
            self.downloads[dl_id] = pending_dl
            has_next = self._has_next_result(chat_id, result_index)
            await status_msg.edit_text(
                f"❌ Download failed: {state}\nFile: `{result.basename}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_retry_next_keyboard(dl_id) if has_next else build_retry_keyboard(dl_id),
            )
            await self._add_history(track, result, "failed")
            return

        source_path = self.processor.find_downloaded_file(result.username, result.filename)
        if not source_path:
            await status_msg.edit_text(
                "❌ Downloaded file not found on disk.\nCheck DOWNLOAD_DIR configuration.",
            )
            await self._add_history(track, result, "file_not_found")
            return

        flac_verdict = await self._analyze_flac(source_path) if result.extension == "flac" else None

        pending_dl = PendingDownload(
            track=track,
            result=result,
            chat_id=chat_id,
            source_path=source_path,
            status_message_id=status_msg.message_id,
            result_index=result_index,
        )
        self.downloads[dl_id] = pending_dl

        quality_line = f"Quality: {result.quality_display} | {result.duration_display}"
        if flac_verdict:
            quality_line += f"\n{flac_verdict.display}"

        await status_msg.edit_text(
            f"✅ *{label} Downloaded!* Sending preview...\n`{result.basename}`\n{quality_line}",
            parse_mode=ParseMode.MARKDOWN,
        )

        file_size = os.path.getsize(source_path) if os.path.isfile(source_path) else 0
        caption = f"{label} {quality_line}\nSave to library?"

        if file_size > TELEGRAM_FILE_LIMIT:
            await self._send_large_file(
                context,
                chat_id,
                track,
                result,
                source_path,
                file_size,
                quality_line,
                label,
                dl_id,
            )
        else:
            target_name = self.processor.build_filename(track.artist, track.title, result.extension)
            try:
                with open(source_path, "rb") as f:
                    sent = await context.bot.send_audio(
                        chat_id=chat_id,
                        audio=f,
                        filename=target_name,
                        title=track.title,
                        performer=track.artist,
                        duration=track.duration_secs,
                        caption=caption,
                        reply_markup=build_approve_keyboard(dl_id),
                    )
            except BadRequest:
                logger.info("send_audio failed, falling back to send_document for %s", result.basename)
                with open(source_path, "rb") as f:
                    sent = await context.bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        filename=target_name,
                        caption=caption,
                        reply_markup=build_approve_keyboard(dl_id),
                    )
            if dl_id in self.downloads:
                self.downloads[dl_id].approval_message_id = sent.message_id

    except asyncio.CancelledError:
        logger.info("Download cancelled for %s", result.basename)
        self.downloads.pop(dl_id, None)
        raise
    except Exception:
        logger.exception(f"Download failed for {result.basename}")
        await status_msg.edit_text(
            f"❌ Error downloading `{result.basename}`. Check logs.",
            parse_mode=ParseMode.MARKDOWN,
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
):
    """Convert a >50 MB file to OGG and send. Trim only as last resort."""
    ogg_path = await self._convert_to_ogg(source_path)

    if ogg_path:
        ogg_size = os.path.getsize(ogg_path)
        if ogg_size <= TELEGRAM_FILE_LIMIT:
            try:
                target_name = self.processor.build_filename(track.artist, track.title, "ogg")
                caption = (
                    f"🎧 {label} Converted to OGG "
                    f"(original: {file_size / (1024 * 1024):.0f}MB {result.extension.upper()})\n"
                    f"{quality_line}\nSave to library?"
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
                        reply_markup=build_approve_keyboard(dl_id),
                    )
                if dl_id in self.downloads:
                    self.downloads[dl_id].approval_message_id = sent.message_id
                return
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
                f"❌ {label} Could not create preview for "
                f"{file_size / (1024 * 1024):.0f}MB file.\n"
                f"{quality_line}\n\nSave to library anyway?"
            ),
            reply_markup=build_approve_keyboard(dl_id),
        )
        if dl_id in self.downloads:
            self.downloads[dl_id].approval_message_id = sent.message_id
        return

    try:
        preview_ext = os.path.splitext(preview_path)[1].lstrip(".")
        target_name = self.processor.build_filename(track.artist, f"{track.title} (1min preview)", preview_ext)
        preview_caption = (
            f"🎧 {label} ~1 min preview "
            f"(full file: {file_size / (1024 * 1024):.0f}MB)\n"
            f"{quality_line}\n"
            f"Save to library?"
        )
        with open(preview_path, "rb") as f:
            sent = await context.bot.send_audio(
                chat_id=chat_id,
                audio=f,
                filename=target_name,
                title=f"{track.title} (1min preview)",
                performer=track.artist,
                duration=60,
                caption=preview_caption,
                reply_markup=build_approve_keyboard(dl_id),
            )
        if dl_id in self.downloads:
            self.downloads[dl_id].approval_message_id = sent.message_id
    finally:
        with contextlib.suppress(OSError):
            os.unlink(preview_path)


async def handle_approval(self, update, context, chat_id: int, data: str):
    """Handle approve/reject of a downloaded file."""
    query = update.callback_query
    action, dl_id = data.split(":", 1)

    pending_dl = self.downloads.pop(dl_id, None)
    if not pending_dl:
        await self._edit_approval_message(query, "⏹ Cancelled")
        return

    if pending_dl.chat_id != chat_id:
        self.downloads[dl_id] = pending_dl
        return

    track = pending_dl.track
    result = pending_dl.result

    if action == "approve":
        if pending_dl.source_path:
            target_path = self.processor.process_file(pending_dl.source_path, track.artist, track.title)
            if target_path:
                self.processor.cleanup_download(pending_dl.source_path)
                await self._embed_spotify_artwork(target_path, track)
                target_name = os.path.basename(target_path)
                await self._edit_approval_message(query, f"✅ Saved: `{target_name}`")
                await self._add_history(track, result, "success")
                logger.info(f"Approved and saved: {target_name}")
                await self._dismiss_other_downloads(context, chat_id)
            else:
                await self._edit_approval_message(query, "❌ Failed to save file. Check logs.")
                await self._add_history(track, result, "process_failed")
        else:
            await self._edit_approval_message(query, "❌ Source file not found.")
            await self._add_history(track, result, "file_not_found")

    elif action == "reject":
        if pending_dl.source_path and os.path.isfile(pending_dl.source_path):
            os.remove(pending_dl.source_path)
            logger.info(f"Deleted rejected file: {pending_dl.source_path}")
        await self._edit_approval_message(query, f"🚫 Rejected: {track.artist} - {track.title}")
        await self._add_history(track, result, "rejected")
        logger.info(f"Rejected: {track.artist} - {track.title} ({result.basename})")


async def dismiss_other_downloads(self, context, chat_id: int):
    """Cancel all remaining pending downloads for a chat after one is approved."""
    pending = self.pending.pop(chat_id, None)
    if pending and pending.message_id:
        with contextlib.suppress(Exception):
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=pending.message_id,
            )

    stale = [(k, v) for k, v in self.downloads.items() if v.chat_id == chat_id]
    for dl_id, dl in stale:
        del self.downloads[dl_id]
        if dl.source_path and os.path.isfile(dl.source_path):
            os.remove(dl.source_path)
        if dl.approval_message_id:
            try:
                await context.bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=dl.approval_message_id,
                    caption="⏹ Cancelled",
                )
            except Exception:
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=dl.approval_message_id,
                        text="⏹ Cancelled",
                    )

    for task in self._active_tasks.pop(chat_id, set()):
        task.cancel()


async def edit_approval_message(query, text: str):
    """Edit the approval message — works for both audio captions and text messages."""
    try:
        await query.edit_message_caption(caption=text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        with contextlib.suppress(Exception):
            await query.edit_message_text(text=text, parse_mode=ParseMode.MARKDOWN)


async def handle_retry(self, update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, data: str):
    """Retry a failed download."""
    query = update.callback_query
    dl_id = data.split(":", 1)[1]

    pending_dl = self.downloads.pop(dl_id, None)
    if not pending_dl:
        await safe_query_edit(query, "⏹ Download expired. Send a new search.")
        return

    if pending_dl.chat_id != chat_id:
        self.downloads[dl_id] = pending_dl
        return

    result = pending_dl.result
    track = pending_dl.track
    result_index = pending_dl.result_index

    await safe_query_edit(
        query,
        f"\U0001f504 Retrying: `{result.basename}`...",
        parse_mode=ParseMode.MARKDOWN,
    )

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"⬇️ Re-downloading from `{result.username}`...",
        parse_mode=ParseMode.MARKDOWN,
    )

    task = context.application.create_task(
        self._do_download(context, chat_id, track, result, status_msg, result_index),
        update=update,
    )
    self._track_task(chat_id, task)


async def handle_next_result(self, update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, data: str):
    """Try the next-best search result after a failed download."""
    query = update.callback_query
    dl_id = data.split(":", 1)[1]

    pending = self.pending.get(chat_id) or self._import_pending.get(chat_id)
    pending_dl = self.downloads.pop(dl_id, None)

    if not pending or not pending.results or not pending_dl:
        await safe_query_edit(query, "⏹ No more results available. Try a new search.")
        return

    if pending_dl.chat_id != chat_id:
        self.downloads[dl_id] = pending_dl
        return

    next_idx = pending_dl.result_index + 1
    if next_idx >= len(pending.results):
        await safe_query_edit(query, "⏹ No more results to try.")
        return

    next_result = pending.results[next_idx]
    track = pending_dl.track

    await safe_query_edit(
        query,
        f"⏭ Trying next result: `{next_result.basename}`",
        parse_mode=ParseMode.MARKDOWN,
    )

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"⬇️ Downloading from `{next_result.username}`...",
        parse_mode=ParseMode.MARKDOWN,
    )

    task = context.application.create_task(
        self._do_download(context, chat_id, track, next_result, status_msg, next_idx),
        update=update,
    )
    self._track_task(chat_id, task)


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
