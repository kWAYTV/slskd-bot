"""Inline keyboard callback dispatch: prefix -> bound conversation handler."""

from __future__ import annotations

import contextlib

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from music_downloader.telegram.ui.editing import safe_query_edit


async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button presses."""
    query = update.callback_query
    with contextlib.suppress(BadRequest):
        await query.answer()

    if not self._is_authorized(query.from_user.id):
        return

    chat_id = update.effective_chat.id
    data = query.data

    prefix = data.split(":", 1)[0]
    handler = {
        "direct": self._handle_direct_search,
        "ic": self._handle_import_callback,
        "ix": self._handle_import_callback,
        "ia": self._handle_import_callback,
        "ir": self._handle_import_callback,
        "is": self._handle_import_callback,
        "iy": self._handle_import_callback,
        "if": self._handle_import_callback,
        "retry": self._handle_retry,
        "next": self._handle_next_result,
        "dup": self._handle_duplicate_response,
        "sp_page": self._handle_spotify_page,
        "sp": self._handle_spotify_selection,
        "dl_page": self._handle_results_page,
        "dl": self._handle_download_selection,
        "approve": self._handle_approval,
        "reject": self._handle_approval,
    }.get(prefix)

    if handler:
        await handler(update, context, chat_id, data)
        return

    if data.startswith("auto:"):
        await _toggle_auto_mode(self, query, chat_id, data)
        return

    if data.startswith("qp:"):
        await _switch_quality_preference(self, query, chat_id, data)
        return


async def _toggle_auto_mode(self, query, chat_id: int, data: str) -> None:
    self._auto_overrides[chat_id] = data == "auto:on"
    mode_str = ("ON") if self.is_auto(chat_id) else ("OFF")
    await safe_query_edit(
        query,
        (f"Auto-download mode: *{mode_str}*"),
        parse_mode="Markdown",
    )


async def _switch_quality_preference(self, query, chat_id: int, data: str) -> None:
    pref = data.split(":", 1)[1]
    if pref in ("cd", "hires"):
        self._quality_overrides[chat_id] = pref
    label = ("CD quality (16/44.1)") if self.quality_pref(chat_id) == "cd" else ("Hi-Res (24-bit)")
    await safe_query_edit(
        query,
        (f"Audio quality preference: *{label}*"),
        parse_mode="Markdown",
    )
