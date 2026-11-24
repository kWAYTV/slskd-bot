"""/cancel and the Cancel-all button: stop everything the chat has queued."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from slskd_importer.telegram.ui.editing import safe_query_edit

logger = logging.getLogger(__name__)


async def cancel_everything(self, chat_id: int) -> str:
    """Cancel the chat's active batches. Returns the i18n key of the outcome."""
    cancelled = await self.runner.cancel_chat(chat_id)
    if cancelled:
        logger.info("chat=%s cancelled %d batch(es)", chat_id, cancelled)
    return "cancel_done" if cancelled else "cancel_nothing"


async def cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await self._check_auth(update):
        return
    chat_id = update.effective_chat.id
    await update.message.reply_text(self.t(chat_id, await cancel_everything(self, chat_id)))


async def handle_cancel_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, data: str):
    """Cancel-all button on /status."""
    await safe_query_edit(update.callback_query, self.t(chat_id, await cancel_everything(self, chat_id)))
