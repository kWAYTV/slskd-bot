"""Retry a failed download or move on to the next-best result."""

from __future__ import annotations

import logging

from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.telegram.ui.editing import safe_query_edit
from slskd_importer.telegram.ui.formatting import track_chip
from slskd_importer.telegram.ui.markdown import md_code_safe
from slskd_importer.telegram.ui.reply import reply_kwargs

logger = logging.getLogger(__name__)


async def handle_retry(self, update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, data: str):
    """Retry a failed download."""
    query = update.callback_query
    dl_id = data.split(":", 1)[1]

    pending_dl = self.downloads.pop(dl_id, None)
    if not pending_dl:
        await safe_query_edit(query, self.t(chat_id, "download_expired"))
        return

    if pending_dl.chat_id != chat_id:
        self.downloads[dl_id] = pending_dl
        return

    result = pending_dl.result
    track = pending_dl.track
    result_index = pending_dl.result_index
    label = f"#{result_index + 1}"
    chip = track_chip(track, label)
    logger.info("chat=%s retrying %s %s", chat_id, label, result.basename)

    await safe_query_edit(
        query,
        self.t(chat_id, "retrying", chip=chip, file=md_code_safe(result.basename)),
        parse_mode=ParseMode.MARKDOWN,
    )

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=self.t(chat_id, "redownloading", chip=chip, user=md_code_safe(result.username)),
        parse_mode=ParseMode.MARKDOWN,
        **reply_kwargs(pending_dl.origin_message_id),
    )
    await self._set_results_pick_state(context, pending_dl.search_id, result_index, "downloading")

    task = context.application.create_task(
        self._do_download(
            context,
            chat_id,
            track,
            result,
            status_msg,
            result_index,
            user_id=pending_dl.user_id,
            search_id=pending_dl.search_id,
        ),
        update=update,
    )
    self._track_task(chat_id, task)


async def handle_next_result(self, update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, data: str):
    """Try the next-best search result after a failed download."""
    query = update.callback_query
    dl_id = data.split(":", 1)[1]

    pending_dl = self.downloads.pop(dl_id, None)
    pending = None
    if pending_dl and pending_dl.search_id:
        pending = self.pending.get(pending_dl.search_id)
    if pending is None:
        pending = self._import_pending.get(chat_id)

    if not pending or not pending.results or not pending_dl:
        if pending_dl:
            self.downloads[dl_id] = pending_dl
        await safe_query_edit(query, self.t(chat_id, "no_more_available"))
        return

    if pending_dl.chat_id != chat_id:
        self.downloads[dl_id] = pending_dl
        return

    next_idx = pending_dl.result_index + 1
    if next_idx >= len(pending.results):
        await safe_query_edit(query, self.t(chat_id, "no_more_results"))
        return

    if pending_dl.source_path:
        await self._cleanup_download_artifacts(pending_dl)

    next_result = pending.results[next_idx]
    track = pending_dl.track
    label = f"#{next_idx + 1}"
    chip = track_chip(track, label)
    logger.info("chat=%s trying next result %s %s", chat_id, label, next_result.basename)

    await safe_query_edit(
        query,
        self.t(chat_id, "trying_next", chip=chip, file=md_code_safe(next_result.basename)),
        parse_mode=ParseMode.MARKDOWN,
    )

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=self.t(chat_id, "downloading_next", chip=chip, user=md_code_safe(next_result.username)),
        parse_mode=ParseMode.MARKDOWN,
        **reply_kwargs(pending_dl.origin_message_id or pending.message_id),
    )
    await self._set_results_pick_state(context, pending_dl.search_id, next_idx, "downloading")

    task = context.application.create_task(
        self._do_download(
            context,
            chat_id,
            track,
            next_result,
            status_msg,
            next_idx,
            user_id=pending_dl.user_id,
            search_id=pending_dl.search_id,
        ),
        update=update,
    )
    self._track_task(chat_id, task)
