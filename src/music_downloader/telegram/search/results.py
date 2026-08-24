"""Ranked result presentation: auto-download or pick keyboard, plus paging."""

from __future__ import annotations

from telegram.constants import ParseMode

from music_downloader.catalog.track import TrackInfo
from music_downloader.soulseek.result import SearchResult
from music_downloader.telegram.core.session import PendingSearch
from music_downloader.telegram.ui.editing import safe_edit
from music_downloader.telegram.ui.formatting import format_search_results
from music_downloader.telegram.ui.keyboards import build_results_keyboard


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
    """Store ranked results and show the pick keyboard."""
    existing = self.pending.get(chat_id)
    self.pending[chat_id] = PendingSearch(
        query=query,
        track=track,
        results=ranked,
        message_id=searching_msg.message_id,
        is_fallback=is_fallback,
        user_id=existing.user_id if existing else None,
    )

    results_text = format_search_results(
        track, ranked, is_fallback=is_fallback, page=0, page_size=self.config.max_results
    )
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
    results_text = format_search_results(
        pending.track,
        pending.results,
        is_fallback=pending.is_fallback,
        page=page,
        page_size=self.config.max_results,
    )
    await query.edit_message_text(
        results_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_results_keyboard(pending.results, page=page, page_size=self.config.max_results),
    )
