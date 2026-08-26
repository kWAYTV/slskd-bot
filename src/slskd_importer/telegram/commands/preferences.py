"""/quality and /lang — per-chat ranking and language preference."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.telegram.ui.keyboards import build_language_keyboard, build_quality_keyboard


async def cmd_quality(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /quality command — choose CD vs Hi-Res preference for result ranking."""
    if not await self._check_auth(update):
        return

    chat_id = update.effective_chat.id
    pref = self.quality_pref(chat_id)
    label_key = "quality_cd" if pref == "cd" else "quality_hires"
    await update.message.reply_text(
        self.t(chat_id, "quality_current", label=self.t(chat_id, label_key)),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_quality_keyboard(pref, locale=self.locale(chat_id)),
    )


async def cmd_lang(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /lang and /language — show the language picker again."""
    if not await self._check_auth(update):
        return

    chat_id = update.effective_chat.id
    await update.message.reply_text(
        self.t(chat_id, "lang_pick"),
        reply_markup=build_language_keyboard(),
    )
