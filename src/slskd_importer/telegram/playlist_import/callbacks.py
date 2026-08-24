"""Import keyboard callbacks: start/cancel job, approve/retry/skip tracks."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.playlist_import.job import JobStatus, TrackStatus
from slskd_importer.telegram.download.approval import save_to_library
from slskd_importer.telegram.ui.editing import safe_query_edit
from slskd_importer.telegram.ui.markdown import md_code_safe

logger = logging.getLogger(__name__)


async def handle_import_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, data: str):
    """Route import-related callbacks (ic/ix/ia/ir/is/iy/if prefixes)."""
    query = update.callback_query
    prefix, _sep, payload = data.partition(":")
    parts = payload.split(":")

    try:
        job_id = int(parts[0])
    except (IndexError, ValueError):
        return

    job = await asyncio.to_thread(self.import_repo.get_job_for_chat, job_id, chat_id)
    if not job:
        await safe_query_edit(query, ("⏹ Import not found."))
        return

    if prefix == "ic":
        await _start_job(self, update, context, chat_id, job_id)
        return
    if prefix == "ix":
        await _cancel_job(self, query, chat_id, job_id)
        return
    if prefix == "ia":
        await self._handle_import_approve(update, context, chat_id, job_id, int(parts[1]), parts[2])
        return
    if prefix == "ir":
        await _discard_track(self, query, context, chat_id, job_id, int(parts[1]))
        return
    if prefix == "is":
        await _skip_track(self, query, context, chat_id, job_id, int(parts[1]))
        return
    if prefix == "iy":
        await self._handle_import_retry(update, context, chat_id, job_id, int(parts[1]), parts[2])
        return
    if prefix == "if":
        await self._handle_import_retry_failed(update, context, chat_id, job_id)


async def _start_job(self, update, context, chat_id: int, job_id: int):
    query = update.callback_query
    await safe_query_edit(query, ("✅ Import started! Progress updates in the next message."))
    logger.info("chat=%s started import job %s", chat_id, job_id)
    await asyncio.to_thread(self.import_repo.update_job_status, job_id, JobStatus.active)
    self._active_import[chat_id] = job_id
    progress_msg = await context.bot.send_message(chat_id=chat_id, text="📋 *Import starting…*", parse_mode="Markdown")
    self._import_status_msg[chat_id] = progress_msg
    generation = self._chat_generation.get(chat_id, 0)
    task = context.application.create_task(
        self._process_next_import_track(context, chat_id, job_id, generation),
        update=update,
    )
    self._track_task(chat_id, task)


async def _cancel_job(self, query, chat_id: int, job_id: int):
    await asyncio.to_thread(self.import_repo.update_job_status, job_id, JobStatus.cancelled)
    self._active_import.pop(chat_id, None)
    logger.info("chat=%s cancelled import job %s via keyboard", chat_id, job_id)
    await safe_query_edit(query, ("❌ Import cancelled."))


async def _discard_track(self, query, context, chat_id: int, job_id: int, track_id: int):
    stale = [k for k, v in self.downloads.items() if v.chat_id == chat_id]
    for stale_id in stale:
        await self._cleanup_download_artifacts(self.downloads.pop(stale_id))
    await asyncio.to_thread(self.import_repo.complete_track, job_id, track_id, TrackStatus.failed, "Rejected by user")
    logger.info("chat=%s import job %s discarded track %s", chat_id, job_id, track_id)
    await safe_query_edit(query, ("🗑 Track discarded."))
    generation = self._chat_generation.get(chat_id, 0)
    await self._process_next_import_track(context, chat_id, job_id, generation)


async def _skip_track(self, query, context, chat_id: int, job_id: int, track_id: int):
    await asyncio.to_thread(self.import_repo.complete_track, job_id, track_id, TrackStatus.skipped)
    logger.info("chat=%s import job %s skipped track %s", chat_id, job_id, track_id)
    await safe_query_edit(query, ("⏭ Track skipped."))
    generation = self._chat_generation.get(chat_id, 0)
    await self._process_next_import_track(context, chat_id, job_id, generation)


async def handle_import_retry(self, update, context, chat_id: int, job_id: int, track_id: int, dl_id: str):
    """Retry a failed import download inside the import flow (keeps job tracking)."""
    query = update.callback_query
    pending_dl = self.downloads.get(dl_id)

    if not pending_dl:
        await safe_query_edit(query, ("⏹ Download expired. Use Skip or Mark failed to continue the import."))
        return

    result = pending_dl.result
    track = pending_dl.track

    await safe_query_edit(
        query,
        (f"🔄 Retrying: `{md_code_safe(result.basename)}`..."),
        parse_mode=ParseMode.MARKDOWN,
    )

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=(f"⬇️ Re-downloading from `{md_code_safe(result.username)}`..."),
        parse_mode=ParseMode.MARKDOWN,
    )

    await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.searching)
    generation = self._chat_generation.get(chat_id, 0)
    task = context.application.create_task(
        self._do_import_download(context, chat_id, track, result, status_msg, generation, job_id, track_id, dl_id),
        update=update,
    )
    self._track_task(chat_id, task)


async def handle_import_approve(self, update, context, chat_id: int, job_id: int, track_id: int, dl_id: str):
    """Approve a download within an import flow."""
    query = update.callback_query

    if not self._can_save_library(query.from_user.id):
        await self._edit_approval_message(query, ("🚫 You are not allowed to save to the library."))
        return

    pending_dl = self.downloads.pop(dl_id, None)

    if not pending_dl:
        await self._edit_approval_message(query, ("⏹ Download expired"))
        return

    if not pending_dl.source_path:
        await self._edit_approval_message(query, ("❌ Source file not ready. Download may still be in progress."))
        self.downloads[dl_id] = pending_dl
        return

    target_name = await save_to_library(self, pending_dl, chat_id)
    if not target_name:
        await self._edit_approval_message(query, ("❌ Failed to save file."))
        await asyncio.to_thread(
            self.import_repo.complete_track, job_id, track_id, TrackStatus.failed, "File processing failed"
        )
        await self._process_next_import_track(context, chat_id, job_id, self._chat_generation.get(chat_id, 0))
        return

    await self._edit_approval_message(query, (f"✅ Saved: `{target_name}`"))
    logger.info("chat=%s import job %s saved track %s as %s", chat_id, job_id, track_id, target_name)
    await asyncio.to_thread(self.import_repo.complete_track, job_id, track_id, TrackStatus.completed)
    await self._process_next_import_track(context, chat_id, job_id, self._chat_generation.get(chat_id, 0))


async def handle_import_retry_failed(self, update, context, chat_id: int, job_id: int):
    """Reset failed tracks to pending and continue the job (summary retry button)."""
    query = update.callback_query

    reset = await asyncio.to_thread(self.import_repo.reset_failed_tracks, job_id)
    if not reset:
        await safe_query_edit(query, ("Nothing to retry — no failed tracks left."))
        return

    await safe_query_edit(
        query,
        (f"🔄 Retrying {reset} failed track(s)..."),
    )
    self._active_import[chat_id] = job_id
    generation = self._chat_generation.get(chat_id, 0)
    task = context.application.create_task(
        self._process_next_import_track(context, chat_id, job_id, generation),
        update=update,
    )
    self._track_task(chat_id, task)
