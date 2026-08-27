"""/lang — per-chat language preference."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from slskd_importer.telegram.commands.keyboards import build_language_keyboard


async def cmd_lang(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /lang and /language — show the language picker again."""
    if not await self._check_auth(update):
        return

    chat_id = update.effective_chat.id
    await update.message.reply_text(
        self.t(chat_id, "lang_pick"),
        reply_markup=build_language_keyboard(),
    )
