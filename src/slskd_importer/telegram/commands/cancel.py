"""/cancel and the Cancel-all button — stop the chat's in-flight search, download, or import."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from slskd_importer.playlist_import.job import JobStatus
from slskd_importer.telegram.ui.editing import safe_query_edit
from slskd_importer.telegram.ui.feedback import unpin

logger = logging.getLogger(__name__)


async def cancel_everything(self, chat_id: int, bot) -> str:
    """Stop the chat's import, searches and downloads. Returns the i18n key of the outcome."""
    job_id = self._active_import.pop(chat_id, None)
    if not job_id:
        active = await asyncio.to_thread(self.import_repo.get_active_job, chat_id)
        job_id = active.id if active else None

    if job_id:
        await asyncio.to_thread(self.import_repo.update_job_status, job_id, JobStatus.cancelled)
        status_msg = self._import_status_msg.get(chat_id)
        await self._cancel_chat_operations(chat_id, bot)
        await unpin(bot, chat_id, getattr(status_msg, "message_id", None))
        logger.info("chat=%s cancelled import job %s", chat_id, job_id)
        return "cancel_import"

    had_work = await self._cancel_chat_operations(chat_id, bot)
    return "cancel_done" if had_work else "cancel_nothing"


async def cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel — cancel active import or search."""
    if not await self._check_auth(update):
        return

    chat_id = update.effective_chat.id
    key = await cancel_everything(self, chat_id, context.bot)
    await update.message.reply_text(self.t(chat_id, key))


async def handle_cancel_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, data: str):
    """Cancel-all button on /status."""
    key = await cancel_everything(self, chat_id, context.bot)
    await safe_query_edit(update.callback_query, self.t(chat_id, key))
