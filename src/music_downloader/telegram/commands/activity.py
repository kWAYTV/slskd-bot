"""/status, /history, /undo, and /cancel — what the bot is doing and undoing it."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from music_downloader.playlist_import.job import JobStatus
from music_downloader.telegram.ui.markdown import code_span, escape_md

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
    lines = _search_lines(self, chat_id) + _download_lines(self, chat_id) + _import_lines(job)

    if not lines:
        await update.message.reply_text("No active searches, downloads, or imports.")
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
    return [("*Active searches:*") + "\n", entry]


def _download_lines(self, chat_id: int) -> list[str]:
    chat_downloads = [dl for dl in self.downloads.values() if dl.chat_id == chat_id]
    if not chat_downloads:
        return []
    lines = ["\n" + ("*Active downloads:*") + "\n"]
    for dl in chat_downloads:
        name = f"{escape_md(dl.track.artist)} - {escape_md(dl.track.title)}"
        lines.append(f"• {name} — {_download_state(dl)} ({code_span(dl.result.basename)})")
    return lines


def _download_state(dl) -> str:
    if dl.source_path:
        return "awaiting approval"
    if dl.progress_percent is not None:
        return f"{dl.progress_percent:.0f}%"
    return "starting..."


def _import_lines(job) -> list[str]:
    if not job:
        return []
    done = job.completed_tracks + job.failed_tracks + job.skipped_tracks
    summary = f"• {escape_md(job.name)} — {done}/{job.total_tracks} processed ({job.completed_tracks} saved, {job.failed_tracks} failed, {job.skipped_tracks} skipped)"
    return ["\n" + ("*Active import:*") + "\n", summary]


async def cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /history command — show recent downloads."""
    if not await self._check_auth(update):
        return

    records = await asyncio.to_thread(self.history_repo.get_recent, 10, update.effective_chat.id)

    if not records:
        await update.message.reply_text("No downloads yet.")
        return

    lines = [("*Recent downloads:*") + "\n"]
    lines.extend(f"{_STATUS_ICONS.get(entry.status, '❌')} {code_span(entry.filename)}" for entry in records)

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_undo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /undo command — remove the last track saved to the library."""
    if not await self._check_library_auth(update):
        return

    chat_id = update.effective_chat.id
    entry = await asyncio.to_thread(self.history_repo.get_last_saved, chat_id)
    if not entry:
        await update.message.reply_text("Nothing to undo — no library saves in this chat.")
        return

    deleted = await asyncio.to_thread(self.processor.delete_library_file, entry.filename)
    if not deleted:
        matches = await asyncio.to_thread(self.processor.find_exact, entry.artist, entry.title)
        if matches:
            deleted = await asyncio.to_thread(self.processor.delete_library_file, matches[0])

    if deleted:
        await asyncio.to_thread(self.history_repo.set_status, entry.id, "undone")
        await update.message.reply_text(
            (f"↩️ Removed from library: {code_span(entry.filename)}"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text(
        (f"Could not find {code_span(entry.filename)} in the library — maybe it was already removed."),
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
        await update.message.reply_text("❌ Import cancelled.")
        return

    active = await asyncio.to_thread(self.import_repo.get_active_job, chat_id)
    if active:
        await asyncio.to_thread(self.import_repo.update_job_status, active.id, JobStatus.cancelled)
        await self._cancel_chat_operations(chat_id)
        await update.message.reply_text("❌ Import cancelled.")
        return

    had_work = await self._cancel_chat_operations(chat_id)
    await update.message.reply_text(("❌ Cancelled.") if had_work else ("Nothing to cancel."))
