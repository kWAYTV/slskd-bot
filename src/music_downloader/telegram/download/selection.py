"""Result pick from the search keyboard — kicks off the download task."""

from __future__ import annotations

import contextlib

from telegram.constants import ParseMode
from telegram.error import BadRequest

from music_downloader.i18n.catalog import gettext as _
from music_downloader.telegram.ui.markdown import escape_md, md_code_safe


async def handle_download_selection(self, update, context, chat_id: int, data: str):
    """Handle when user picks a file to download from results."""
    query = update.callback_query
    pending = self.pending.get(chat_id)
    if not pending:
        await query.edit_message_text(_("Search expired. Send a new query."))
        return

    action = data.split(":", 1)[1]

    if action == "cancel":
        del self.pending[chat_id]
        await query.edit_message_text(_("Cancelled."))
        return

    if action == "auto":
        index = 0
    else:
        try:
            index = int(action)
        except ValueError:
            return

    if index >= len(pending.results):
        return

    result = pending.results[index]
    track = pending.track
    user_id = pending.user_id or query.from_user.id

    with contextlib.suppress(BadRequest):
        await query.edit_message_reply_markup(reply_markup=None)

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=(
            _("⬇️ *Downloading #{n}...*\n{artist} - {title}\nFrom: `{user}`\nFile: `{file}`").format(
                n=index + 1,
                artist=escape_md(track.artist),
                title=escape_md(track.title),
                user=md_code_safe(result.username),
                file=md_code_safe(result.basename),
            )
        ),
        parse_mode=ParseMode.MARKDOWN,
    )

    task = context.application.create_task(
        self._do_download(context, chat_id, track, result, status_msg, index, user_id=user_id),
        update=update,
    )
    self._track_task(chat_id, task)


def has_next_result(self, chat_id: int, current_index: int) -> bool:
    pending = self.pending.get(chat_id)
    return pending is not None and current_index + 1 < len(pending.results)
