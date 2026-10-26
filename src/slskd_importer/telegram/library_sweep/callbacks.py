"""Callback handlers for sweep decisions (`swp:`) and decline reasons (`swr:`)."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from slskd_importer.records.sweep_models import DECISION_KEEP_MINE, DECLINE_REASONS
from slskd_importer.sweep.outcomes import SweepError
from slskd_importer.telegram.library_sweep.keyboards import SWEEP_CHOICES, SWEEP_REASONS, build_sweep_reason_keyboard
from slskd_importer.telegram.ui.editing import safe_query_edit
from slskd_importer.telegram.ui.markdown import escape_md

logger = logging.getLogger(__name__)


def _sweep_allowed(self, user_id: int) -> bool:
    return user_id in self.sweep.users and self._can_save_library(user_id)


async def handle_sweep_decision(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, data: str):
    """`swp:<id>:m|n|b` — Keep mine / Take new / Keep both."""
    query = update.callback_query
    if not _sweep_allowed(self, query.from_user.id):
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
        await safe_query_edit(query, f"Could not apply: {escape_md(str(exc))}")
        return

    if decision == DECISION_KEEP_MINE:
        await safe_query_edit(
            query,
            f"Kept yours for `{escape_md(review.stem)}`. What was wrong with the copy?",
            reply_markup=build_sweep_reason_keyboard(review.id),
        )
        return

    label = {"take_new": "Took the new copy", "keep_both": "Kept both"}.get(decision, decision)
    await safe_query_edit(query, f"{label}: `{escape_md(path)}`")


async def handle_sweep_reason(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, data: str):
    """`swr:<id>:d|m|v|o` — optional why after Keep mine."""
    query = update.callback_query
    if not _sweep_allowed(self, query.from_user.id):
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
        await safe_query_edit(query, "Reason not stored (already set or not Keep mine).")
        return
    await safe_query_edit(query, f"Noted: `{escape_md(reason)}`.")
