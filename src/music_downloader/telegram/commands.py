"""Telegram command handlers: /start, /help, /auto, /status, /history."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from music_downloader.telegram.keyboards import build_auto_mode_keyboard


async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if not await self._check_auth(update):
        return

    await update.message.reply_text(
        "Send me a song name (e.g., `Nancy Sinatra Bang Bang`) "
        "and I'll find and download it in FLAC.\n\n"
        "Commands:\n"
        "/auto — Toggle auto-download mode\n"
        "/status — Show active downloads\n"
        "/history — Recent downloads\n"
        "/help — Show this message",
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

    mode_str = "ON" if self.auto_mode else "OFF"
    await update.message.reply_text(
        f"Auto-download mode is currently: *{mode_str}*\n\n"
        "When ON, the best FLAC match is downloaded automatically without asking you to pick.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_auto_mode_keyboard(self.auto_mode),
    )


async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command — show active searches and downloads."""
    if not await self._check_auth(update):
        return

    lines = []

    if self.pending:
        lines.append("*Active searches:*\n")
        for _chat_id, pending in self.pending.items():
            lines.append(f"• {pending.track.artist} - {pending.track.title}")

    if self.downloads:
        lines.append("\n*Active downloads:*\n")
        for _dl_id, dl in self.downloads.items():
            lines.append(f"• {dl.track.artist} - {dl.track.title} ({dl.result.basename})")

    if not lines:
        await update.message.reply_text("No active searches or downloads.")
        return

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /history command — show recent downloads."""
    if not await self._check_auth(update):
        return

    records = await asyncio.to_thread(self.history_repo.get_recent, 10)

    if not records:
        await update.message.reply_text("No downloads yet.")
        return

    lines = ["*Recent downloads:*\n"]
    for entry in records:
        icon = {"success": "✅", "rejected": "🚫"}.get(entry.status, "❌")
        lines.append(f"{icon} `{entry.filename}`")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
