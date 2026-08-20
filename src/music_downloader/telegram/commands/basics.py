"""/start and /help — the welcome card."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from music_downloader.telegram.ui.formatting import welcome_text


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
