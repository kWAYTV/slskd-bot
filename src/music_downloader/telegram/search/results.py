"""Ranked result presentation: auto-download or pick keyboard, plus paging."""

from __future__ import annotations

from telegram.constants import ParseMode

from music_downloader.catalog.track import TrackInfo
from music_downloader.soulseek.result import SearchResult
from music_downloader.telegram.core.session import PendingSearch
from music_downloader.telegram.ui.editing import safe_edit
from music_downloader.telegram.ui.formatting import format_result_reasons, track_md
from music_downloader.telegram.ui.keyboards import build_results_keyboard
from music_downloader.telegram.ui.markdown import md_code_safe


async def present_search_results(
    self,
    context,
    chat_id: int,
    track: TrackInfo,
    ranked: list[SearchResult],
    is_fallback: bool,
    searching_msg,
    query: str,
):
    """Store ranked results and either auto-download or show the pick keyboard."""
    existing = self.pending.get(chat_id)
    self.pending[chat_id] = PendingSearch(
        query=query,
        track=track,
        results=ranked,
        message_id=searching_msg.message_id,
        is_fallback=is_fallback,
        user_id=existing.user_id if existing else None,
    )

    if self.is_auto(chat_id):
        header = track_md(track)
        await safe_edit(
            searching_msg,
            (f"⚡ Auto-downloading best match for {header}..."),
            parse_mode=ParseMode.MARKDOWN,
        )
        result = ranked[0]
        text = f"⬇️ *Downloading #{1}...*\n{header}\nFrom: `{md_code_safe(result.username)}`\nFile: `{md_code_safe(result.basename)}`"
        reasons = format_result_reasons(track, result)
        if reasons:
            text += f"\n{reasons}"
        status_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
        user_id = self.pending[chat_id].user_id if chat_id in self.pending else None
        task = context.application.create_task(
            self._do_download(context, chat_id, track, result, status_msg, 0, user_id=user_id),
        )
        self._track_task(chat_id, task)
        return

    results_text = self._format_results(track, ranked, is_fallback, page=0, page_size=self.config.max_results)
    await safe_edit(
        searching_msg,
        results_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_results_keyboard(ranked, page=0, page_size=self.config.max_results),
    )


async def handle_results_page(self, update, context, chat_id: int, data: str):
    """Handle slskd results page navigation (◀️ / ▶️)."""
    query = update.callback_query
    pending = self.pending.get(chat_id)
    if not pending or not pending.track:
        await query.edit_message_text("Search expired. Send a new query.")
        return

    try:
        page = int(data.split(":", 1)[1])
    except ValueError:
        return

    pending.page = page
    results_text = self._format_results(
        pending.track,
        pending.results,
        pending.is_fallback,
        page=page,
        page_size=self.config.max_results,
    )
    await query.edit_message_text(
        results_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_results_keyboard(pending.results, page=page, page_size=self.config.max_results),
    )
