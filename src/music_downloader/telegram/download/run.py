"""The download run: transfer, verify, deliver a preview, ask for approval."""

from __future__ import annotations

import asyncio
import logging
import os

from telegram.constants import ParseMode

from music_downloader.catalog.track import TrackInfo
from music_downloader.i18n.catalog import gettext as _
from music_downloader.soulseek.result import SearchResult
from music_downloader.telegram.core.session import PendingDownload
from music_downloader.telegram.download.delivery import send_audio_or_document
from music_downloader.telegram.download.transfer import fetch_from_peer, make_progress_callback
from music_downloader.telegram.ui.editing import safe_edit
from music_downloader.telegram.ui.formatting import format_flac_verdict, format_result_reasons, progress_bar
from music_downloader.telegram.ui.keyboards import (
    build_approve_keyboard,
    build_retry_keyboard,
    build_retry_next_keyboard,
)
from music_downloader.telegram.ui.markdown import escape_md, md_code_safe

logger = logging.getLogger(__name__)


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

    async def _render_progress(pct: float) -> None:
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
        outcome = await fetch_from_peer(self, result, make_progress_callback(pending_dl, _render_progress))
        if not outcome.enqueued:
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

        status = outcome.status
        transfer_id = status.transfer_id if status else pending_dl.transfer_id
        pending_dl.transfer_id = transfer_id

        if outcome.failed:
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

        source_path = outcome.source_path
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
        reasons = format_result_reasons(track, result)
        if reasons:
            quality_line += f"\n{reasons}"
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
        if file_size > self.config.telegram_file_limit:
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
            sent = await send_audio_or_document(
                context,
                chat_id,
                source_path,
                filename=self.processor.build_filename(track.artist, track.title, result.extension),
                title=track.title,
                performer=track.artist,
                duration=track.duration_secs,
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
