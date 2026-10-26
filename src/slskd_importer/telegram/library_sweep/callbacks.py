"""Callback handlers for sweep decisions (`swp:`) and decline reasons (`swr:`)."""

from __future__ import annotations

import logging

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from slskd_importer.records.sweep_models import DECISION_KEEP_MINE, DECLINE_REASONS
from slskd_importer.sweep.outcomes import SweepError
from slskd_importer.telegram.library_sweep.keyboards import SWEEP_CHOICES, SWEEP_REASONS, build_sweep_reason_keyboard
from slskd_importer.telegram.ui.editing import edit_approval_message
from slskd_importer.telegram.ui.markdown import escape_md

logger = logging.getLogger(__name__)

_CLEAR_KEYBOARD = InlineKeyboardMarkup([])


def _sweep_allowed(self, user_id: int) -> bool:
    return user_id in self.sweep.users and self._can_save_library(user_id)


async def handle_sweep_decision(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, data: str):
    """`swp:<id>:m|n|b` — Keep mine / Take new / Keep both."""
    query = update.callback_query
    if not _sweep_allowed(self, query.from_user.id):
        await edit_approval_message(query, "Not allowed to change the library.", reply_markup=_CLEAR_KEYBOARD)
        return
    try:
        _, rid, code = data.split(":", 2)
        review_id = int(rid)
        decision = SWEEP_CHOICES[code]
    except (ValueError, KeyError):
        logger.warning("Bad sweep decision callback: %s", data)
        return

    try:
        review, path = await self.sweep.decide(review_id, decision)
    except SweepError as exc:
        await edit_approval_message(query, f"Could not apply: {escape_md(str(exc))}", reply_markup=_CLEAR_KEYBOARD)
        return
    except Exception as exc:
        logger.exception("Sweep decision %s failed for pair %s", decision, review_id)
        await edit_approval_message(
            query, f"Could not apply: {escape_md(f'{type(exc).__name__}: {exc}')}", reply_markup=_CLEAR_KEYBOARD
        )
        return

    if decision == DECISION_KEEP_MINE:
        await edit_approval_message(
            query,
            f"Kept yours for `{escape_md(review.stem)}`. What was wrong with the copy?",
            reply_markup=build_sweep_reason_keyboard(review.id),
        )
        return

    label = {"take_new": "Took the new copy", "keep_both": "Kept both"}.get(decision, decision)
    name = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    await edit_approval_message(query, f"{label}: `{escape_md(name)}`", reply_markup=_CLEAR_KEYBOARD)


async def handle_sweep_reason(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, data: str):
    """`swr:<id>:d|m|v|o` — optional why after Keep mine."""
    query = update.callback_query
    if not _sweep_allowed(self, query.from_user.id):
        await edit_approval_message(query, "Not allowed to change the library.", reply_markup=_CLEAR_KEYBOARD)
        return
    try:
        _, rid, code = data.split(":", 2)
        review_id = int(rid)
        reason = SWEEP_REASONS[code]
    except (ValueError, KeyError):
        logger.warning("Bad sweep reason callback: %s", data)
        return
    if reason not in DECLINE_REASONS:
        return
    ok = await __import__("asyncio").to_thread(self.sweep.repo.set_decline_reason, review_id, reason)
    if not ok:
        await edit_approval_message(
            query, "Reason not stored (already set or not Keep mine).", reply_markup=_CLEAR_KEYBOARD
        )
        return
    await edit_approval_message(query, f"Noted: `{escape_md(reason)}`.", reply_markup=_CLEAR_KEYBOARD)
