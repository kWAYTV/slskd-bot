"""Telegram command handlers: /start, /help, /auto, /status, /history."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from music_downloader.i18n.catalog import gettext as _
from music_downloader.telegram.keyboards import build_auto_mode_keyboard
from music_downloader.telegram.messages import code_span, escape_md, welcome_text


async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if not await self._check_auth(update):
        return

    await update.message.reply_text(
        welcome_text(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    if not await self._check_auth(update):
        return
    await self.cmd_start(update, context)


async def cmd_auto(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /auto command — toggle auto-download mode."""
    if not await self._check_auth(update):
        return

    is_auto = self.is_auto(update.effective_chat.id)
    mode_str = _("ON") if is_auto else _("OFF")
    await update.message.reply_text(
        _(
            "Auto-download mode is currently: *{mode}*\n\nWhen ON, the best FLAC match is downloaded automatically without asking you to pick."
        ).format(mode=mode_str),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_auto_mode_keyboard(is_auto),
    )


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
        }.get(entry.status, "❌")
        lines.append(f"{icon} {code_span(entry.filename)}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
