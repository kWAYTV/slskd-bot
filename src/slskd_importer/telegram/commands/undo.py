"""/undo and history-row undo — remove a library save."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.telegram.ui.markdown import code_span

logger = logging.getLogger(__name__)


async def cmd_undo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /undo command — remove the last track saved to the library."""
    if not await self._check_library_auth(update):
        return

    chat_id = update.effective_chat.id
    entry = await asyncio.to_thread(self.history_repo.get_last_saved, chat_id)
    if not entry:
        await update.message.reply_text(self.t(chat_id, "undo_nothing"))
        return

    deleted = await _remove_library_save(self, entry)
    if deleted:
        logger.info("chat=%s undid library save %s", chat_id, entry.filename)
        await update.message.reply_text(
            self.t(chat_id, "undo_removed", filename=code_span(entry.filename)),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text(
        self.t(chat_id, "undo_missing", filename=code_span(entry.filename)),
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_history_undo(self, update, context, chat_id: int, data: str):
    """Inline ↩️ on /history — undo a specific successful save."""
    query = update.callback_query
    if not self._can_save_library(query.from_user.id):
        await query.edit_message_text(self.t(chat_id, "auth_library_undo"))
        return
    try:
        entry_id = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return

    entry = await asyncio.to_thread(self.history_repo.get_for_chat, entry_id, chat_id)
    if not entry or entry.status != "success":
        await query.edit_message_text(self.t(chat_id, "undo_gone"))
        return

    deleted = await _remove_library_save(self, entry)
    if deleted:
        logger.info("chat=%s undid history id=%s %s", chat_id, entry.id, entry.filename)
        await query.edit_message_text(
            self.t(chat_id, "undo_removed", filename=code_span(entry.filename)),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await query.edit_message_text(
        self.t(chat_id, "undo_missing", filename=code_span(entry.filename)),
        parse_mode=ParseMode.MARKDOWN,
    )


async def _remove_library_save(self, entry) -> bool:
    """Delete the library file for a history row and mark it undone."""
    deleted = await asyncio.to_thread(self.processor.delete_library_file, entry.filename)
    if not deleted:
        matches = await asyncio.to_thread(self.processor.find_exact, entry.artist, entry.title)
        if matches:
            deleted = await asyncio.to_thread(self.processor.delete_library_file, matches[0])
    if deleted:
        await asyncio.to_thread(self.history_repo.set_status, entry.id, "undone")
    return deleted
