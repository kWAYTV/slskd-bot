"""/status, /history, /undo, and /cancel — what the bot is doing and undoing it."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from music_downloader.i18n.catalog import gettext as _
from music_downloader.playlist_import.job import JobStatus
from music_downloader.telegram.ui.markdown import code_span, escape_md


async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command — show active searches, downloads, and imports."""
    if not await self._check_auth(update):
        return

    chat_id = update.effective_chat.id
    lines = []

    pending = self.pending.get(chat_id)
    if pending:
        lines.append(_("*Active searches:*") + "\n")
        if pending.track:
            lines.append(f"• {escape_md(pending.track.artist)} - {escape_md(pending.track.title)}")
        else:
            lines.append(f"• {code_span(pending.query)}")

    chat_downloads = [dl for dl in self.downloads.values() if dl.chat_id == chat_id]
    if chat_downloads:
        lines.append("\n" + _("*Active downloads:*") + "\n")
        for dl in chat_downloads:
            name = f"{escape_md(dl.track.artist)} - {escape_md(dl.track.title)}"
            if dl.source_path:
                state = _("awaiting approval")
            elif dl.progress_percent is not None:
                state = f"{dl.progress_percent:.0f}%"
            else:
                state = _("starting...")
            lines.append(f"• {name} — {state} ({code_span(dl.result.basename)})")

    job = await asyncio.to_thread(self.import_repo.get_active_job, chat_id)
    if job:
        done = job.completed_tracks + job.failed_tracks + job.skipped_tracks
        lines.append("\n" + _("*Active import:*") + "\n")
        lines.append(
            _("• {name} — {done}/{total} processed ({ok} saved, {failed} failed, {skipped} skipped)").format(
                name=escape_md(job.name),
                done=done,
                total=job.total_tracks,
                ok=job.completed_tracks,
                failed=job.failed_tracks,
                skipped=job.skipped_tracks,
            )
        )

    if not lines:
        await update.message.reply_text(_("No active searches, downloads, or imports."))
        return

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /history command — show recent downloads."""
    if not await self._check_auth(update):
        return

    records = await asyncio.to_thread(self.history_repo.get_recent, 10, update.effective_chat.id)

    if not records:
        await update.message.reply_text(_("No downloads yet."))
        return

    lines = [_("*Recent downloads:*") + "\n"]
    for entry in records:
        icon = {
            "success": "✅",
            "rejected": "🚫",
            "failed": "❌",
            "file_not_found": "❓",
            "process_failed": "⚠️",
            "delivered": "📲",
            "undone": "↩️",
        }.get(entry.status, "❌")
        lines.append(f"{icon} {code_span(entry.filename)}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_undo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /undo command — remove the last track saved to the library."""
    if not await self._check_library_auth(update):
        return

    chat_id = update.effective_chat.id
    entry = await asyncio.to_thread(self.history_repo.get_last_saved, chat_id)
    if not entry:
        await update.message.reply_text(_("Nothing to undo — no library saves in this chat."))
        return

    deleted = await asyncio.to_thread(self.processor.delete_library_file, entry.filename)
    if not deleted:
        matches = await asyncio.to_thread(self.processor.find_exact, entry.artist, entry.title)
        if matches:
            deleted = await asyncio.to_thread(self.processor.delete_library_file, matches[0])

    if deleted:
        await asyncio.to_thread(self.history_repo.set_status, entry.id, "undone")
        await update.message.reply_text(
            _("↩️ Removed from library: {name}").format(name=code_span(entry.filename)),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text(
        _("Could not find {name} in the library — maybe it was already removed.").format(
            name=code_span(entry.filename)
        ),
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
        await update.message.reply_text(_("❌ Import cancelled."))
        return

    active = await asyncio.to_thread(self.import_repo.get_active_job, chat_id)
    if active:
        await asyncio.to_thread(self.import_repo.update_job_status, active.id, JobStatus.cancelled)
        await self._cancel_chat_operations(chat_id)
        await update.message.reply_text(_("❌ Import cancelled."))
        return

    had_work = await self._cancel_chat_operations(chat_id)
    if had_work:
        await update.message.reply_text(_("❌ Cancelled."))
    else:
        await update.message.reply_text(_("Nothing to cancel."))
