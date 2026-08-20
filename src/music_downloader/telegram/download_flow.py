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
from music_downloader.i18n.catalog import gettext as _
from music_downloader.library.artwork import embed_artwork_into_file, fetch_spotify_artwork
from music_downloader.library.flac import FlacVerdict, analyze_flac
from music_downloader.library.preview import convert_to_ogg, create_preview_clip
from music_downloader.soulseek.result import SearchResult
from music_downloader.telegram.keyboards import (
    build_approve_keyboard,
    build_retry_keyboard,
    build_retry_next_keyboard,
)
from music_downloader.telegram.messages import (
    escape_md,
    format_flac_verdict,
    md_code_safe,
    progress_bar,
    safe_edit,
    safe_query_edit,
)
from music_downloader.telegram.session import PendingDownload

logger = logging.getLogger(__name__)

TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024


async def handle_download_selection(self, update, context, chat_id: int, data: str):
    """Handle when user picks a file to download from results."""
    query = update.callback_query
    pending = self.pending.get(chat_id)
    if not pending:
        await query.edit_message_text(_("Search expired. Send a new query."))
        return

    action = data.split(":", 1)[1]

    if action == "cancel":
        del self.pending[chat_id]
        await query.edit_message_text(_("Cancelled."))
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
    user_id = pending.user_id or query.from_user.id

    with contextlib.suppress(BadRequest):
        await query.edit_message_reply_markup(reply_markup=None)

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=(
            _("⬇️ *Downloading #{n}...*\n{artist} - {title}\nFrom: `{user}`\nFile: `{file}`").format(
                n=index + 1,
                artist=escape_md(track.artist),
                title=escape_md(track.title),
                user=md_code_safe(result.username),
                file=md_code_safe(result.basename),
            )
        ),
        parse_mode=ParseMode.MARKDOWN,
    )

    task = context.application.create_task(
        self._do_download(context, chat_id, track, result, status_msg, index, user_id=user_id),
        update=update,
    )
    self._track_task(chat_id, task)


def has_next_result(self, chat_id: int, current_index: int) -> bool:
    pending = self.pending.get(chat_id)
    return pending is not None and current_index + 1 < len(pending.results)


async def do_download(
    self,
    context,
    chat_id: int,
    track: TrackInfo,
    result: SearchResult,
    status_msg,
    result_index: int = 0,
    user_id: int | None = None,
):
    """Download a file, send it to Telegram for preview, and ask for approval."""
    dl_id = self._next_dl_id()
    label = f"#{result_index + 1}"
    can_save = self._can_save_library(user_id)
    transfer_id = None

    # Register up front so /status and /cancel see in-flight downloads.
    pending_dl = PendingDownload(
        track=track,
        result=result,
        chat_id=chat_id,
        status_message_id=status_msg.message_id,
        result_index=result_index,
        user_id=user_id,
    )
    self.downloads[dl_id] = pending_dl

    last_edited_pct = -100.0

    async def _on_progress(progress) -> None:
        nonlocal last_edited_pct
        pct = progress.percent_complete
        pending_dl.progress_percent = pct
        pending_dl.transfer_id = progress.transfer_id or pending_dl.transfer_id
        if pct - last_edited_pct < 10:
            return
        last_edited_pct = pct
        await safe_edit(
            status_msg,
            _("⬇️ *Downloading {label}...* {pct}%\n{bar}\n{artist} - {title}\nFile: `{file}`").format(
                label=label,
                pct=f"{pct:.0f}",
                bar=progress_bar(pct),
                artist=escape_md(track.artist),
                title=escape_md(track.title),
                file=md_code_safe(result.basename),
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

    try:
        success = await asyncio.to_thread(self.slskd.enqueue_download, result)
        if not success:
            has_next = self._has_next_result(chat_id, result_index)
            await safe_edit(
                status_msg,
                _("❌ Failed to enqueue download from `{user}`.\nThe user might be offline.").format(
                    user=md_code_safe(result.username)
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_retry_next_keyboard(dl_id) if has_next else build_retry_keyboard(dl_id),
            )
            return

        status = await self.slskd.wait_for_download(
            username=result.username,
            filename=result.filename,
            timeout_secs=self.config.download_timeout_secs,
            progress_callback=_on_progress,
        )
        transfer_id = status.transfer_id if status else pending_dl.transfer_id
        pending_dl.transfer_id = transfer_id

        if status is None or status.is_failed:
            state = status.state if status else _("Timeout")
            has_next = self._has_next_result(chat_id, result_index)
            await safe_edit(
                status_msg,
                _("❌ Download failed: {state}\nFile: `{file}`").format(
                    state=state, file=md_code_safe(result.basename)
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_retry_next_keyboard(dl_id) if has_next else build_retry_keyboard(dl_id),
            )
            await self._add_history(track, result, "failed", chat_id=chat_id)
            return

        source_path = self.processor.find_downloaded_file(result.username, result.filename)
        if not source_path:
            self.downloads.pop(dl_id, None)
            await safe_edit(
                status_msg,
                _("❌ Downloaded file not found on disk.\nCheck DOWNLOAD_DIR configuration."),
            )
            await self._add_history(track, result, "file_not_found", chat_id=chat_id)
            return

        flac_verdict = await self._analyze_flac(source_path) if result.extension == "flac" else None

        pending_dl.source_path = source_path
        pending_dl.progress_percent = 100.0

        quality_line = _("Quality: {quality} | {duration}").format(
            quality=result.quality_display, duration=result.duration_display
        )
        if flac_verdict:
            quality_line += f"\n{format_flac_verdict(flac_verdict)}"

        await safe_edit(
            status_msg,
            _("✅ *{label} Downloaded!* Sending preview...\n`{file}`\n{quality}").format(
                label=label, file=md_code_safe(result.basename), quality=quality_line
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

        file_size = os.path.getsize(source_path) if os.path.isfile(source_path) else 0
        caption = (
            _("{label} {quality}\nSave to library?").format(label=label, quality=quality_line)
            if can_save
            else _("{label} {quality}\nSent to you — not saved to the library.").format(
                label=label, quality=quality_line
            )
        )
        markup = (
            build_approve_keyboard(dl_id, has_next=self._has_next_result(chat_id, result_index)) if can_save else None
        )

        delivered = True
        if file_size > TELEGRAM_FILE_LIMIT:
            delivered = await self._send_large_file(
                context,
                chat_id,
                track,
                result,
                source_path,
                file_size,
                quality_line,
                label,
                dl_id,
                reply_markup=markup,
                can_save=can_save,
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
                        reply_markup=markup,
                    )
            except BadRequest:
                logger.info("send_audio failed, falling back to send_document for %s", result.basename)
                with open(source_path, "rb") as f:
                    sent = await context.bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        filename=target_name,
                        caption=caption,
                        reply_markup=markup,
                    )
            if dl_id in self.downloads:
                self.downloads[dl_id].approval_message_id = sent.message_id

        if not can_save:
            # Only record "delivered" when audio actually reached the user.
            status = "delivered" if delivered else "failed"
            await _forget_local_copy(self, pending_dl, track, result, chat_id, status=status)

    except asyncio.CancelledError:
        logger.info("Download cancelled for %s", result.basename)
        pending_dl = self.downloads.pop(dl_id, None)
        if pending_dl:
            await self._cleanup_download_artifacts(pending_dl)
        else:
            await asyncio.to_thread(self.slskd.cancel_transfer, result.username, result.filename, transfer_id)
        raise
    except Exception:
        logger.exception(f"Download failed for {result.basename}")
        has_next = self._has_next_result(chat_id, result_index)
        await safe_edit(
            status_msg,
            _("❌ Error downloading `{file}`. Check logs.").format(file=md_code_safe(result.basename)),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_retry_next_keyboard(dl_id) if has_next else build_retry_keyboard(dl_id),
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
                caption = _("🎧 {label} Converted to OGG (original: {size:.0f}MB {fmt})\n{quality}\n").format(
                    label=label,
                    size=file_size / (1024 * 1024),
                    fmt=result.extension.upper(),
                    quality=quality_line,
                ) + (_("Save to library?") if can_save else _("Sent to you — not saved to the library."))
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


async def handle_approval(self, update, context, chat_id: int, data: str):
    """Handle approve/reject of a downloaded file."""
    query = update.callback_query
    action, dl_id = data.split(":", 1)

    pending_dl = self.downloads.pop(dl_id, None)
    if not pending_dl:
        await self._edit_approval_message(query, _("⏹ Cancelled"))
        return

    if pending_dl.chat_id != chat_id:
        self.downloads[dl_id] = pending_dl
        return

    track = pending_dl.track
    result = pending_dl.result

    if action == "approve":
        if not self._can_save_library(query.from_user.id):
            self.downloads[dl_id] = pending_dl
            await self._edit_approval_message(query, _("🚫 You are not allowed to save to the library."))
            return
        if pending_dl.source_path:
            target_path = self.processor.process_file(pending_dl.source_path, track.artist, track.title)
            if target_path:
                await self._remove_download_file(pending_dl.source_path)
                await self._embed_spotify_artwork(target_path, track)
                target_name = os.path.basename(target_path)
                await self._edit_approval_message(query, _("✅ Saved: `{name}`").format(name=target_name))
                await self._add_history(track, result, "success", chat_id=chat_id)
                logger.info(f"Approved and saved: {target_name}")
                await self._dismiss_other_downloads(context, chat_id)
            else:
                await self._edit_approval_message(query, _("❌ Failed to save file. Check logs."))
                await self._add_history(track, result, "process_failed", chat_id=chat_id)
        else:
            await self._edit_approval_message(query, _("❌ Source file not found."))
            await self._add_history(track, result, "file_not_found", chat_id=chat_id)

    elif action == "reject":
        await self._cleanup_download_artifacts(pending_dl)
        await self._edit_approval_message(
            query,
            _("🚫 Rejected: {artist} - {title}").format(artist=escape_md(track.artist), title=escape_md(track.title)),
        )
        await self._add_history(track, result, "rejected", chat_id=chat_id)
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
        await self._cleanup_download_artifacts(dl)
        if dl.approval_message_id:
            try:
                await context.bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=dl.approval_message_id,
                    caption=_("⏹ Cancelled"),
                )
            except Exception:
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=dl.approval_message_id,
                        text=_("⏹ Cancelled"),
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
        await safe_query_edit(query, _("⏹ Download expired. Send a new search."))
        return

    if pending_dl.chat_id != chat_id:
        self.downloads[dl_id] = pending_dl
        return

    result = pending_dl.result
    track = pending_dl.track
    result_index = pending_dl.result_index
    label = f"#{result_index + 1}"

    await safe_query_edit(
        query,
        _("🔄 Retrying {label}: `{file}`...").format(label=label, file=md_code_safe(result.basename)),
        parse_mode=ParseMode.MARKDOWN,
    )

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=_("⬇️ Re-downloading {label} from `{user}`...").format(label=label, user=md_code_safe(result.username)),
        parse_mode=ParseMode.MARKDOWN,
    )

    task = context.application.create_task(
        self._do_download(context, chat_id, track, result, status_msg, result_index, user_id=pending_dl.user_id),
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
        await safe_query_edit(query, _("⏹ No more results available. Try a new search."))
        return

    if pending_dl.chat_id != chat_id:
        self.downloads[dl_id] = pending_dl
        return

    next_idx = pending_dl.result_index + 1
    if next_idx >= len(pending.results):
        await safe_query_edit(query, _("⏹ No more results to try."))
        return

    if pending_dl.source_path:
        await self._cleanup_download_artifacts(pending_dl)

    next_result = pending.results[next_idx]
    track = pending_dl.track
    label = f"#{next_idx + 1}"

    await safe_query_edit(
        query,
        _("⏭ Trying next result {label}: `{file}`").format(label=label, file=md_code_safe(next_result.basename)),
        parse_mode=ParseMode.MARKDOWN,
    )

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=_("⬇️ Downloading {label} from `{user}`...").format(label=label, user=md_code_safe(next_result.username)),
        parse_mode=ParseMode.MARKDOWN,
    )

    task = context.application.create_task(
        self._do_download(context, chat_id, track, next_result, status_msg, next_idx, user_id=pending_dl.user_id),
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


async def _forget_local_copy(
    self,
    pending_dl: PendingDownload,
    track: TrackInfo,
    result: SearchResult,
    chat_id: int,
    status: str = "delivered",
):
    """Send-only users: drop the local file and slskd transfer after Telegram delivery."""
    for key, value in list(self.downloads.items()):
        if value is pending_dl:
            del self.downloads[key]
            break
    await self._cleanup_download_artifacts(pending_dl)
    await self._add_history(track, result, status, chat_id=chat_id)


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
