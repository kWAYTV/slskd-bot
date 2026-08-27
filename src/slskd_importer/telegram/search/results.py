"""Ranked result presentation: auto-download or pick keyboard, plus paging."""

from __future__ import annotations

from telegram.constants import ParseMode

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.telegram.core.session import PendingSearch, split_search_callback
from slskd_importer.telegram.search.keyboards import build_results_keyboard
from slskd_importer.telegram.ui.editing import safe_edit, safe_query_edit
from slskd_importer.telegram.ui.formatting import format_search_results


async def present_search_results(
    self,
    context,
    chat_id: int,
    track: TrackInfo,
    ranked: list[SearchResult],
    is_fallback: bool,
    searching_msg,
    query: str,
    search_id: str,
):
    """Store ranked results and show the pick keyboard."""
    existing = self.pending.get(search_id)
    self.pending[search_id] = PendingSearch(
        query=query,
        track=track,
        results=ranked,
        message_id=searching_msg.message_id,
        is_fallback=is_fallback,
        user_id=existing.user_id if existing else None,
        search_id=search_id,
        chat_id=chat_id,
    )

    results_text = format_search_results(
        track,
        ranked,
        is_fallback=is_fallback,
        page=0,
        page_size=self.config.max_results,
        locale=self.locale(chat_id),
    )
    await safe_edit(
        searching_msg,
        results_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_results_keyboard(
            ranked, page=0, page_size=self.config.max_results, search_id=search_id, locale=self.locale(chat_id)
        ),
    )


async def handle_results_page(self, update, context, chat_id: int, data: str):
    """Handle slskd results page navigation (◀️ / ▶️)."""
    query = update.callback_query
    parsed = split_search_callback(data)
    if not parsed:
        return
    search_id, page_raw = parsed
    pending = self.pending.get(search_id)
    if not pending or not pending.track:
        await safe_query_edit(query, self.t(chat_id, "search_expired"))
        return

    try:
        page = int(page_raw)
    except ValueError:
        return

    pending.page = page
    results_text = format_search_results(
        pending.track,
        pending.results,
        is_fallback=pending.is_fallback,
        page=page,
        page_size=self.config.max_results,
        locale=self.locale(chat_id),
    )
    await safe_query_edit(
        query,
        results_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_results_keyboard(
            pending.results,
            page=page,
            page_size=self.config.max_results,
            search_id=search_id,
            locale=self.locale(chat_id),
        ),
    )
