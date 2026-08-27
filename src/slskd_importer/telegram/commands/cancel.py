"""/cancel — stop the chat's in-flight search, download, or import."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from slskd_importer.playlist_import.job import JobStatus

logger = logging.getLogger(__name__)


async def cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel — cancel active import or search."""
    if not await self._check_auth(update):
        return

    chat_id = update.effective_chat.id

    job_id = self._active_import.pop(chat_id, None)
    if job_id:
        await asyncio.to_thread(self.import_repo.update_job_status, job_id, JobStatus.cancelled)
        await self._cancel_chat_operations(chat_id, context.bot)
        logger.info("chat=%s cancelled import job %s", chat_id, job_id)
        await update.message.reply_text(self.t(chat_id, "cancel_import"))
        return

    active = await asyncio.to_thread(self.import_repo.get_active_job, chat_id)
    if active:
        await asyncio.to_thread(self.import_repo.update_job_status, active.id, JobStatus.cancelled)
        await self._cancel_chat_operations(chat_id, context.bot)
        logger.info("chat=%s cancelled import job %s", chat_id, active.id)
        await update.message.reply_text(self.t(chat_id, "cancel_import"))
        return

    had_work = await self._cancel_chat_operations(chat_id, context.bot)
    await update.message.reply_text(self.t(chat_id, "cancel_done" if had_work else "cancel_nothing"))
