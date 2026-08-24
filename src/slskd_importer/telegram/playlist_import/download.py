"""Download one import track and ask for save approval."""

from __future__ import annotations

import asyncio
import logging
import os

from telegram.constants import ParseMode

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.playlist_import.job import TrackStatus
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.telegram.core.session import PendingDownload
from slskd_importer.telegram.download.delivery import send_audio_or_document
from slskd_importer.telegram.download.transfer import abort_transfer, fetch_from_peer, make_progress_callback
from slskd_importer.telegram.ui.editing import safe_edit
from slskd_importer.telegram.ui.formatting import progress_bar
from slskd_importer.telegram.ui.keyboards import build_import_failure_keyboard, build_import_track_keyboard
from slskd_importer.telegram.ui.markdown import escape_md, md_code_safe

logger = logging.getLogger(__name__)


async def do_import_download(
    self,
    context,
    chat_id: int,
    track: TrackInfo,
    result: SearchResult,
    status_msg,
    generation: int,
    job_id: int,
    track_id: int,
    dl_id: str,
):
    """Download a file within an import flow."""
    # Registered by the import search; fall back to a detached record if expired.
    pending_dl = self.downloads.get(dl_id) or PendingDownload(track=track, result=result, chat_id=chat_id)

    async def _render_progress(pct: float) -> None:
        queued = pending_dl.transfer_state and "queued" in pending_dl.transfer_state.lower()
        line = "⌛ queued at peer" if queued else f"⬇️ Downloading {pct:.0f}%\n{progress_bar(pct)}"
        await safe_edit(
            status_msg,
            (
                f"📋 *Import track:* {escape_md(track.artist)} - {escape_md(track.title)}\n{line}\n`{md_code_safe(result.basename)}`"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

    try:
        outcome = await fetch_from_peer(self, result, make_progress_callback(pending_dl, _render_progress))
        if not outcome.enqueued:
            await safe_edit(
                status_msg,
                (f"❌ Failed to enqueue from `{md_code_safe(result.username)}`"),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_import_track_keyboard(job_id, track_id, dl_id),
            )
            await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.awaiting_approval)
            return

        status = outcome.status
        if status and status.transfer_id:
            pending_dl.transfer_id = status.transfer_id

        if outcome.failed:
            state = status.state if status else ("Timeout")
            await safe_edit(
                status_msg,
                (f"❌ Download failed: {state}\n`{md_code_safe(result.basename)}`"),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_import_failure_keyboard(job_id, track_id, dl_id),
            )
            await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.awaiting_approval)
            return

        source_path = outcome.source_path
        if not source_path:
            await safe_edit(
                status_msg,
                ("❌ Downloaded file not found on disk."),
                reply_markup=build_import_track_keyboard(job_id, track_id, dl_id),
            )
            await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.awaiting_approval)
            return

        pending_dl.source_path = source_path

        await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.awaiting_approval)

        await _deliver_import_preview(
            self, context, chat_id, track, result, status_msg, source_path, job_id, track_id, dl_id
        )

    except asyncio.CancelledError:
        await abort_transfer(self, dl_id, result)
        raise
    except Exception:
        logger.exception(f"Import download failed for {result.basename}")
        await safe_edit(
            status_msg,
            (f"❌ Error downloading `{md_code_safe(result.basename)}`"),
            parse_mode=ParseMode.MARKDOWN,
        )
        await asyncio.to_thread(self.import_repo.complete_track, job_id, track_id, TrackStatus.failed, "Download error")
        await self._process_next_import_track(context, chat_id, job_id, generation)


async def _deliver_import_preview(
    self,
    context,
    chat_id: int,
    track: TrackInfo,
    result: SearchResult,
    status_msg,
    source_path,
    job_id,
    track_id,
    dl_id,
):
    """Send the downloaded audio, or a size notice when it exceeds the Telegram limit."""
    file_size = os.path.getsize(source_path) if os.path.isfile(source_path) else 0
    quality_line = f"{result.quality_display} | {result.duration_display}"
    keyboard = build_import_track_keyboard(job_id, track_id, dl_id)

    if file_size > self.config.telegram_file_limit:
        await safe_edit(
            status_msg,
            (
                f"✅ Downloaded: `{md_code_safe(result.basename)}` ({file_size / (1024 * 1024):.0f}MB)\n{quality_line}\n\nFile too large to preview. Save to library?"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )
        return

    caption = f"📋 Import: {track.artist} - {track.title}\n{quality_line}"
    await send_audio_or_document(
        context,
        chat_id,
        source_path,
        filename=self.processor.build_filename(track.artist, track.title, result.extension),
        title=track.title,
        performer=track.artist,
        duration=track.duration_secs,
        caption=caption,
        reply_markup=keyboard,
    )
