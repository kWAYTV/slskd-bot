"""/status: what the chat has in the queue right now."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.queue.batch import OPEN_STATUSES
from slskd_importer.telegram.commands.keyboards import build_status_keyboard
from slskd_importer.telegram.ui.markdown import escape_md


async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await self._check_auth(update):
        return

    chat_id = update.effective_chat.id
    batches = await asyncio.to_thread(self.queue_store.active_batches, chat_id)
    if not batches:
        await update.message.reply_text(self.t(chat_id, "status_empty"))
        return

    lines = [self.t(chat_id, "status_header"), ""]
    for batch in batches:
        counts = await asyncio.to_thread(self.queue_store.counts, batch.id)
        total = sum(counts.values())
        settled = total - sum(counts.get(status, 0) for status in OPEN_STATUSES)
        lines.append(f"• {escape_md(batch.name)}  ·  {settled} / {total}")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_status_keyboard(locale=self.locale(chat_id)),
    )
