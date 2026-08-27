"""Ranked result presentation: pick keyboard, paging, and live pick-state."""

from __future__ import annotations

import contextlib
import logging

from telegram import InlineKeyboardMarkup
from telegram.constants import ParseMode

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.telegram.core.session import PendingSearch, split_search_callback
from slskd_importer.telegram.search.keyboards import build_results_keyboard, build_results_status_keyboard
from slskd_importer.telegram.ui.editing import safe_edit, safe_query_edit
from slskd_importer.telegram.ui.formatting import format_search_results, track_chip

logger = logging.getLogger(__name__)

_CANCELABLE_STATES = frozenset({"downloading", "failed"})


def render_results_card(self, pending: PendingSearch) -> tuple[str, InlineKeyboardMarkup]:
    """Build the results message text + keyboard from current pick state."""
    locale = self.locale(pending.chat_id)
    status_line = ""
    if pending.picked_index is not None and pending.pick_state and pending.track:
        label = f"#{pending.picked_index + 1}"
        status_line = self.t(
            pending.chat_id,
            f"results_status_{pending.pick_state}",
            chip=track_chip(pending.track, label),
        )
    text = format_search_results(
        pending.track,
        pending.results,
        is_fallback=pending.is_fallback,
        page=pending.page,
        page_size=self.config.max_results,
        locale=locale,
        picked_index=pending.picked_index,
        pick_state=pending.pick_state,
        status_line=status_line,
    )
    if pending.picked_index is not None and pending.pick_state:
        label = f"#{pending.picked_index + 1}"
        markup = build_results_status_keyboard(
            label=self.t(pending.chat_id, f"btn_status_{pending.pick_state}", label=label),
            search_id=pending.search_id,
            show_cancel=pending.pick_state in _CANCELABLE_STATES,
            locale=locale,
        )
    else:
        markup = build_results_keyboard(
            pending.results,
            page=pending.page,
            page_size=self.config.max_results,
            search_id=pending.search_id,
            locale=locale,
        )
    return text, markup


async def set_results_pick_state(self, context, search_id: str | None, index: int, state: str) -> None:
    """Highlight a result on the parent card and lock the keyboard to that pick."""
    if not search_id:
        return
    pending = self.pending.get(search_id)
    if not pending or not pending.track or not pending.message_id:
        return
    pending.picked_index = index
    pending.pick_state = state
    text, markup = render_results_card(self, pending)
    with contextlib.suppress(Exception):
        await context.bot.edit_message_text(
            chat_id=pending.chat_id,
            message_id=pending.message_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=markup,
        )


async def restore_results_picks(self, context, search_id: str | None, note: str = "") -> None:
    """Unlock the results card after discard so the user can pick again."""
    if not search_id:
        return
    pending = self.pending.get(search_id)
    if not pending or not pending.track or not pending.message_id:
        return
    pending.picked_index = None
    pending.pick_state = ""
    locale = self.locale(pending.chat_id)
    text = format_search_results(
        pending.track,
        pending.results,
        is_fallback=pending.is_fallback,
        page=pending.page,
        page_size=self.config.max_results,
        locale=locale,
        status_line=note,
    )
    markup = build_results_keyboard(
        pending.results,
        page=pending.page,
        page_size=self.config.max_results,
        search_id=pending.search_id,
        locale=locale,
    )
    with contextlib.suppress(Exception):
        await context.bot.edit_message_text(
            chat_id=pending.chat_id,
            message_id=pending.message_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=markup,
        )


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
    text, markup = render_results_card(self, pending)
    await safe_query_edit(
        query,
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=markup,
    )
