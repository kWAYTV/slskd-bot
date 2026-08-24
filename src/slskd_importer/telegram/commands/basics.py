"""/start and /help — the welcome card, plus the command menu."""

from __future__ import annotations

from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.telegram.ui.formatting import welcome_text

BOT_COMMANDS = [
    BotCommand("start", "How to search and download"),
    BotCommand("help", "Show help"),
    BotCommand("quality", "Prefer CD or Hi-Res audio"),
    BotCommand("status", "Active searches and downloads"),
    BotCommand("history", "Recent downloads"),
    BotCommand("stats", "Download and library stats"),
    BotCommand("undo", "Remove the last saved track"),
    BotCommand("import", "Import a Spotify playlist or album"),
    BotCommand("cancel", "Cancel the current operation"),
]


async def register_bot_commands(application) -> None:
    await application.bot.set_my_commands(BOT_COMMANDS)


async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start and /help — one welcome card covers both."""
    if not await self._check_auth(update):
        return

    await update.message.reply_text(
        welcome_text(),
        parse_mode=ParseMode.MARKDOWN,
    )
