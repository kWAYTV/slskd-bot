"""/history — recent downloads for this chat."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.telegram.commands.keyboards import build_history_keyboard
from slskd_importer.telegram.ui.markdown import code_span, escape_md

_STATUS_ICONS = {
    "success": "✅",
    "rejected": "🚫",
    "failed": "❌",
    "file_not_found": "❓",
    "process_failed": "⚠️",
    "delivered": "📲",
    "undone": "↩️",
}


async def cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /history command — show recent downloads."""
    if not await self._check_auth(update):
        return

    chat_id = update.effective_chat.id
    records = await asyncio.to_thread(self.history_repo.get_recent, 10, chat_id)

    if not records:
        await update.message.reply_text(self.t(chat_id, "history_empty"))
        return

    lines = [self.t(chat_id, "history_header"), ""]
    for entry in records:
        icon = _STATUS_ICONS.get(entry.status, "❌")
        artist = escape_md(entry.artist)
        title = escape_md(entry.title)
        lines.append(f"{icon}  *{artist} — {title}*\n    {code_span(entry.filename)}")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_history_keyboard(records),
    )
