"""/status, /history, /undo, and /cancel — what the bot is doing and undoing it."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.playlist_import.job import JobStatus
from slskd_importer.telegram.ui.keyboards import build_history_keyboard
from slskd_importer.telegram.ui.markdown import code_span, escape_md

logger = logging.getLogger(__name__)

_STATUS_ICONS = {
    "success": "✅",
    "rejected": "🚫",
    "failed": "❌",
    "file_not_found": "❓",
    "process_failed": "⚠️",
    "delivered": "📲",
    "undone": "↩️",
}


async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command — show active searches, downloads, and imports."""
    if not await self._check_auth(update):
        return

    chat_id = update.effective_chat.id
    job = await asyncio.to_thread(self.import_repo.get_active_job, chat_id)
    lines = _search_lines(self, chat_id) + _download_lines(self, chat_id) + _import_lines(self, chat_id, job)

    if not lines:
        await update.message.reply_text(self.t(chat_id, "status_empty"))
        return

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


def _search_lines(self, chat_id: int) -> list[str]:
    pending = self.pending.get(chat_id)
    if not pending:
        return []
    if pending.track:
        entry = f"• {escape_md(pending.track.artist)} - {escape_md(pending.track.title)}"
    else:
        entry = f"• {code_span(pending.query)}"
    return [self.t(chat_id, "status_searches") + "\n", entry]


def _download_lines(self, chat_id: int) -> list[str]:
    chat_downloads = [dl for dl in self.downloads.values() if dl.chat_id == chat_id]
    if not chat_downloads:
        return []
    lines = ["\n" + self.t(chat_id, "status_downloads") + "\n"]
    for dl in chat_downloads:
        name = f"{escape_md(dl.track.artist)} - {escape_md(dl.track.title)}"
        lines.append(f"• {name} — {_download_state(self, chat_id, dl)} ({code_span(dl.result.basename)})")
    return lines


def _download_state(self, chat_id: int, dl) -> str:
    if dl.source_path:
        return self.t(chat_id, "status_awaiting")
    if dl.transfer_state and "queued" in dl.transfer_state.lower():
        return self.t(chat_id, "status_queued")
    if dl.progress_percent is not None:
        return f"{dl.progress_percent:.0f}%"
    return self.t(chat_id, "status_starting")


def _import_lines(self, chat_id: int, job) -> list[str]:
    if not job:
        return []
    done = job.completed_tracks + job.failed_tracks + job.skipped_tracks
    summary = self.t(
        chat_id,
        "status_import_line",
        name=escape_md(job.name),
        done=done,
        total=job.total_tracks,
        saved=job.completed_tracks,
        failed=job.failed_tracks,
        skipped=job.skipped_tracks,
    )
    return ["\n" + self.t(chat_id, "status_import") + "\n", summary]


async def cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /history command — show recent downloads."""
    if not await self._check_auth(update):
        return

    chat_id = update.effective_chat.id
    records = await asyncio.to_thread(self.history_repo.get_recent, 10, chat_id)

    if not records:
        await update.message.reply_text(self.t(chat_id, "history_empty"))
        return

    lines = [self.t(chat_id, "history_header") + "\n"]
    lines.extend(f"{_STATUS_ICONS.get(entry.status, '❌')} {code_span(entry.filename)}" for entry in records)

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_history_keyboard(records),
    )


async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats — chat download totals and library size."""
    if not await self._check_auth(update):
        return

    chat_id = update.effective_chat.id
    stats = await asyncio.to_thread(self.history_repo.summarize, chat_id)
    files, nbytes = await asyncio.to_thread(self.processor.library_stats)
    rate = f"{(stats.success / stats.total * 100):.0f}%" if stats.total else "—"
    lines = [
        self.t(chat_id, "stats_header") + "\n",
        self.t(
            chat_id,
            "stats_totals",
            total=stats.total,
            success=stats.success,
            failed=stats.failed,
            rejected=stats.rejected,
        ),
        self.t(chat_id, "stats_extra", undone=stats.undone, delivered=stats.delivered),
        self.t(chat_id, "stats_rate", rate=rate),
        self.t(chat_id, "stats_library", files=files, mb=f"{nbytes / (1024 * 1024):.0f}"),
    ]
    if stats.top_sources:
        lines.append("\n" + self.t(chat_id, "stats_sources"))
        lines.extend(f"• {escape_md(user)} — {n}" for user, n in stats.top_sources)
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def handle_history_undo(self, update, context, chat_id: int, data: str):
    """Inline ↩️ on /history — undo a specific successful save."""
    query = update.callback_query
    if not self._can_save_library(query.from_user.id):
        await query.edit_message_text(self.t(chat_id, "auth_library_undo"))
        return
    try:
        entry_id = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return

    entry = await asyncio.to_thread(self.history_repo.get_for_chat, entry_id, chat_id)
    if not entry or entry.status != "success":
        await query.edit_message_text(self.t(chat_id, "undo_gone"))
        return

    deleted = await asyncio.to_thread(self.processor.delete_library_file, entry.filename)
    if not deleted:
        matches = await asyncio.to_thread(self.processor.find_exact, entry.artist, entry.title)
        if matches:
            deleted = await asyncio.to_thread(self.processor.delete_library_file, matches[0])

    if deleted:
        await asyncio.to_thread(self.history_repo.set_status, entry.id, "undone")
        logger.info("chat=%s undid history id=%s %s", chat_id, entry.id, entry.filename)
        await query.edit_message_text(
            self.t(chat_id, "undo_removed", filename=code_span(entry.filename)),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await query.edit_message_text(
        self.t(chat_id, "undo_missing", filename=code_span(entry.filename)),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_undo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /undo command — remove the last track saved to the library."""
    if not await self._check_library_auth(update):
        return

    chat_id = update.effective_chat.id
    entry = await asyncio.to_thread(self.history_repo.get_last_saved, chat_id)
    if not entry:
        await update.message.reply_text(self.t(chat_id, "undo_nothing"))
        return

    deleted = await asyncio.to_thread(self.processor.delete_library_file, entry.filename)
    if not deleted:
        matches = await asyncio.to_thread(self.processor.find_exact, entry.artist, entry.title)
        if matches:
            deleted = await asyncio.to_thread(self.processor.delete_library_file, matches[0])

    if deleted:
        await asyncio.to_thread(self.history_repo.set_status, entry.id, "undone")
        logger.info("chat=%s undid library save %s", chat_id, entry.filename)
        await update.message.reply_text(
            self.t(chat_id, "undo_removed", filename=code_span(entry.filename)),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text(
        self.t(chat_id, "undo_missing", filename=code_span(entry.filename)),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel — cancel active import or search."""
    if not await self._check_auth(update):
        return

    chat_id = update.effective_chat.id

    job_id = self._active_import.pop(chat_id, None)
    if job_id:
        await asyncio.to_thread(self.import_repo.update_job_status, job_id, JobStatus.cancelled)
        await self._cancel_chat_operations(chat_id)
        logger.info("chat=%s cancelled import job %s", chat_id, job_id)
        await update.message.reply_text(self.t(chat_id, "cancel_import"))
        return

    active = await asyncio.to_thread(self.import_repo.get_active_job, chat_id)
    if active:
        await asyncio.to_thread(self.import_repo.update_job_status, active.id, JobStatus.cancelled)
        await self._cancel_chat_operations(chat_id)
        logger.info("chat=%s cancelled import job %s", chat_id, active.id)
        await update.message.reply_text(self.t(chat_id, "cancel_import"))
        return

    had_work = await self._cancel_chat_operations(chat_id)
    await update.message.reply_text(self.t(chat_id, "cancel_done" if had_work else "cancel_nothing"))
