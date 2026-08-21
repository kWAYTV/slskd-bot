"""Result pick from the search keyboard — kicks off the download task."""

from __future__ import annotations

import contextlib

from telegram.constants import ParseMode
from telegram.error import BadRequest

from music_downloader.telegram.ui.markdown import escape_md, md_code_safe


async def handle_download_selection(self, update, context, chat_id: int, data: str):
    """Handle when user picks a file to download from results."""
    query = update.callback_query
    pending = self.pending.get(chat_id)
    if not pending:
        await query.edit_message_text("Search expired. Send a new query.")
        return

    action = data.split(":", 1)[1]

    if action == "cancel":
        del self.pending[chat_id]
        await query.edit_message_text("Cancelled.")
        return

    index = _parse_result_index(action)
    if index is None or index >= len(pending.results):
        return

    result = pending.results[index]
    track = pending.track
    user_id = pending.user_id or query.from_user.id

    with contextlib.suppress(BadRequest):
        await query.edit_message_reply_markup(reply_markup=None)

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"⬇️ *Downloading #{index + 1}...*\n{escape_md(track.artist)} - {escape_md(track.title)}\nFrom: `{md_code_safe(result.username)}`\nFile: `{md_code_safe(result.basename)}`"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )

    task = context.application.create_task(
        self._do_download(context, chat_id, track, result, status_msg, index, user_id=user_id),
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


def has_next_result(self, chat_id: int, current_index: int) -> bool:
    pending = self.pending.get(chat_id)
    return pending is not None and current_index + 1 < len(pending.results)
