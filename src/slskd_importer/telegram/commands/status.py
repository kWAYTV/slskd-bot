"""/status and /stats — what the bot is doing right now."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.telegram.ui.markdown import code_span, escape_md


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


def _search_lines(self, chat_id: int) -> list[str]:
    searches = self._session.searches_for_chat(chat_id)
    if not searches:
        return []
    lines = [self.t(chat_id, "status_searches") + "\n"]
    for pending in searches:
        if pending.track:
            lines.append(f"• {escape_md(pending.track.artist)} — {escape_md(pending.track.title)}")
        else:
            lines.append(f"• {code_span(pending.query)}")
    return lines


def _download_lines(self, chat_id: int) -> list[str]:
    chat_downloads = [dl for dl in self.downloads.values() if dl.chat_id == chat_id]
    if not chat_downloads:
        return []
    lines = ["\n" + self.t(chat_id, "status_downloads") + "\n"]
    for dl in chat_downloads:
        label = f"#{dl.result_index + 1}"
        name = f"{escape_md(dl.track.artist)} — {escape_md(dl.track.title)}"
        lines.append(f"• {label} · {name} — {_download_state(self, chat_id, dl)}")
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
