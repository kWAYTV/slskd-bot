"""/stats: the chat's download totals and the library's size."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.telegram.ui.markdown import escape_md


async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await self._check_auth(update):
        return

    chat_id = update.effective_chat.id
    stats = await asyncio.to_thread(self.history_repo.summarize, chat_id)
    files, nbytes = await asyncio.to_thread(self.processor.library_stats)
    rate = f"{(stats.success / stats.total * 100):.0f}%" if stats.total else "—"
    lines = [
        self.t(chat_id, "stats_header") + "\n",
        self.t(chat_id, "stats_totals", total=stats.total, success=stats.success, failed=stats.failed),
        self.t(chat_id, "stats_extra", undone=stats.undone, delivered=stats.delivered),
        self.t(chat_id, "stats_rate", rate=rate),
        self.t(chat_id, "stats_library", files=files, mb=f"{nbytes / (1024 * 1024):.0f}"),
    ]
    if stats.top_sources:
        lines.append("\n" + self.t(chat_id, "stats_sources"))
        lines.extend(f"• {escape_md(user)} — {n}" for user, n in stats.top_sources)
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
