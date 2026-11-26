"""Inline keyboard callback dispatch: prefix -> bound conversation handler."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from slskd_importer.telegram.card import actions
from slskd_importer.telegram.i18n import LABELS, LOCALES
from slskd_importer.telegram.ui.editing import safe_query_edit

logger = logging.getLogger(__name__)


# Toast shown on the tap itself, before the handler edits anything.
_TOASTS = {
    "hu": "toast_removing",
    "cu": "toast_removing",
    "cancel_all": "toast_cancelled",
}
_CARD_TOASTS = {
    actions.CANCEL: "toast_cancelled",
    actions.RETRY_FAILED: "toast_retrying",
    actions.RETRY: "toast_retrying",
    actions.AGAIN: "toast_downloading",
    actions.GET: "toast_downloading",
    actions.UNDO: "toast_removing",
    actions.SEND: "toast_sending",
    actions.SKIP: "toast_skipped",
    actions.SKIP_ALL: "toast_skipped",
    actions.KEEP: "toast_kept",
}


def toast_key(data: str) -> str | None:
    """The i18n key of the toast for a callback, or None for silent taps (navigation)."""
    action = actions.decode(data)
    if action is not None:
        return _CARD_TOASTS.get(action.name)
    return _TOASTS.get(data.partition(":")[0])


async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button presses."""
    query = update.callback_query
    chat_id = update.effective_chat.id
    data = query.data
    authorized = self._is_authorized(query.from_user.id)
    key = toast_key(data) if authorized else None
    with contextlib.suppress(BadRequest):
        await query.answer(text=self.t(chat_id, key) if key else None)

    if not authorized:
        return

    logger.debug("Callback chat=%s user=%s data=%s", chat_id, query.from_user.id, data)

    prefix = data.split(":", 1)[0]
    handler = {
        actions.PREFIX: self._handle_card_action,
        "hu": self._handle_history_undo,
        "cu": self._handle_check_undo,
        "sb": self._handle_bring_card,
        "cancel_all": self._handle_cancel_all,
    }.get(prefix)

    if handler:
        await handler(update, context, chat_id, data)
        return

    if prefix == "lang":
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
        await safe_query_edit(query, self.t(chat_id, "welcome"), parse_mode="Markdown")
        return
    await safe_query_edit(
        query,
        self.t(chat_id, "lang_set", language=LABELS[self.locale(chat_id)]),
        parse_mode="Markdown",
    )
