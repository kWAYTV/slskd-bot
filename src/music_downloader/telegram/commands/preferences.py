"""/auto and /quality — per-chat download preferences."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from music_downloader.telegram.ui.keyboards import build_auto_mode_keyboard, build_quality_keyboard


async def cmd_auto(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /auto command — toggle auto-download mode."""
    if not await self._check_auth(update):
        return

    is_auto = self.is_auto(update.effective_chat.id)
    mode_str = "ON" if is_auto else "OFF"
    await update.message.reply_text(
        (
            f"Auto-download mode is currently: *{mode_str}*\n\nWhen ON, the best FLAC match is downloaded automatically without asking you to pick."
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_auto_mode_keyboard(is_auto),
    )


async def cmd_quality(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /quality command — choose CD vs Hi-Res preference for result ranking."""
    if not await self._check_auth(update):
        return

    pref = self.quality_pref(update.effective_chat.id)
    label = "CD quality (16/44.1)" if pref == "cd" else "Hi-Res (24-bit)"
    await update.message.reply_text(
        (
            f"Audio quality preference: *{label}*\n\n"
            "This changes how search results are ranked — the preferred format scores higher."
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_quality_keyboard(pref),
    )
