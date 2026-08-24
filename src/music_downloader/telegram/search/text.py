"""Free-text message entry point — song queries and link detection."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from music_downloader.telegram.search.links import handle_link_query

logger = logging.getLogger(__name__)


async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free-text messages — treat as song search queries."""
    if not await self._check_auth(update):
        return

    query = update.message.text.strip()
    if not query:
        return

    chat_id = update.effective_chat.id

    if await handle_link_query(self, update, context, chat_id, query):
        return

    await self._cancel_chat_operations(chat_id)
    generation = self._chat_generation[chat_id]
    logger.info("chat=%s user=%s search query=%r", chat_id, update.effective_user.id, query)
    await self._do_search(update, context, query, generation)
