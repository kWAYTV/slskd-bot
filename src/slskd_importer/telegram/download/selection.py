"""Result pick from the search keyboard — kicks off the download task."""

from __future__ import annotations

import logging

from telegram.constants import ParseMode

from slskd_importer.telegram.core.session import split_search_callback
from slskd_importer.telegram.search.results import render_results_card
from slskd_importer.telegram.ui.editing import safe_query_edit
from slskd_importer.telegram.ui.formatting import track_chip
from slskd_importer.telegram.ui.markdown import md_code_safe
from slskd_importer.telegram.ui.reply import reply_kwargs

logger = logging.getLogger(__name__)


async def handle_download_selection(self, update, context, chat_id: int, data: str):
    """Handle when user picks a file to download from results."""
    query = update.callback_query
    parsed = split_search_callback(data)
    if not parsed:
        return
    search_id, action = parsed
    pending = self.pending.get(search_id)
    if not pending:
        await safe_query_edit(query, self.t(chat_id, "search_expired"))
        return

    if action == "cancel":
        await self._dismiss_other_downloads(context, chat_id, search_id=search_id)
        await safe_query_edit(query, self.t(chat_id, "cancelled"))
        return

    index = _parse_result_index(action)
    if index is None or index >= len(pending.results):
        return

    result = pending.results[index]
    track = pending.track
    user_id = pending.user_id or query.from_user.id
    label = f"#{index + 1}"
    logger.info(
        "chat=%s search=%s selected #%d %s from %s",
        chat_id,
        search_id,
        index + 1,
        result.basename,
        result.username,
    )

    pending.picked_index = index
    pending.pick_state = "downloading"
    text, markup = render_results_card(self, pending)
    await safe_query_edit(query, text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup)

    chip = track_chip(track, label)
    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=self.t(
            chat_id,
            "downloading",
            chip=chip,
            user=md_code_safe(result.username),
            file=md_code_safe(result.basename),
        ),
        parse_mode=ParseMode.MARKDOWN,
        **reply_kwargs(pending.message_id),
    )

    task = context.application.create_task(
        self._do_download(context, chat_id, track, result, status_msg, index, user_id=user_id, search_id=search_id),
        update=update,
    )
    self._track_task(chat_id, task)


def _parse_result_index(action: str) -> int | None:
    """'auto' picks the top result; otherwise the action is a numeric index."""
    if action == "auto":
        return 0
    try:
        return int(action)
    except ValueError:
        return None


def has_next_result(self, chat_id: int, current_index: int, search_id: str | None = None) -> bool:
    pending = self.pending.get(search_id) if search_id else None
    if pending is None:
        pending = self._import_pending.get(chat_id)
    return pending is not None and current_index + 1 < len(pending.results)
