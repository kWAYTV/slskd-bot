"""Inline keyboard callback dispatch: prefix -> bound conversation handler."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from slskd_importer.telegram.i18n import LABELS, LOCALES
from slskd_importer.telegram.ui.editing import safe_query_edit
from slskd_importer.telegram.ui.formatting import welcome_text

logger = logging.getLogger(__name__)


async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button presses."""
    query = update.callback_query
    with contextlib.suppress(BadRequest):
        await query.answer()

    if not self._is_authorized(query.from_user.id):
        return

    chat_id = update.effective_chat.id
    data = query.data
    logger.debug("Callback chat=%s user=%s data=%s", chat_id, query.from_user.id, data)

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
        "sp_page": self._handle_spotify_page,
        "sp": self._handle_spotify_selection,
        "dl_page": self._handle_results_page,
        "dl": self._handle_download_selection,
        "approve": self._handle_approval,
        "reject": self._handle_approval,
        "hu": self._handle_history_undo,
    }.get(prefix)

    if prefix == "lock":
        return

    if handler:
        await handler(update, context, chat_id, data)
        return

    if data.startswith("lang:"):
        await _switch_locale(self, query, chat_id, data)
        return

    logger.warning("Unknown callback prefix %r from chat %s", prefix, chat_id)


async def _switch_locale(self, query, chat_id: int, data: str) -> None:
    code = data.split(":", 1)[1]
    if code not in LOCALES:
        return
    first = self.set_locale(chat_id, code)
    await asyncio.to_thread(self.prefs_repo.set_locale, chat_id, self.locale(chat_id))
    logger.info("chat=%s locale=%s first=%s", chat_id, self.locale(chat_id), first)
    if first:
        await safe_query_edit(query, welcome_text(self.locale(chat_id)), parse_mode="Markdown")
        return
    await safe_query_edit(
        query,
        self.t(chat_id, "lang_set", language=LABELS[self.locale(chat_id)]),
        parse_mode="Markdown",
    )
