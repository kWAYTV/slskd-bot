"""`/sweep` command: start, force, stop, status, reviews."""

from __future__ import annotations

import logging
import time

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.telegram.library_sweep.pairs import send_sweep_pairs
from slskd_importer.telegram.library_sweep.report import status_text
from slskd_importer.telegram.ui.markdown import escape_md

logger = logging.getLogger(__name__)

_HELP = (
    "`/sweep` starts a sweep now, `/sweep force` checks every song, "
    "`/sweep stop` cancels the running one, `/sweep status` shows progress, "
    "`/sweep reviews` sends waiting pairs."
)


async def cmd_sweep(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """`/sweep` starts a sweep; status / reviews / force / stop."""
    if not await self._check_library_auth(update):
        return
    user_id = update.effective_user.id
    if user_id not in self.sweep.users:
        await update.message.reply_text("The library sweep is not on for this account.")
        return

    arg = (context.args[0].lower() if context.args else "").strip()
    sweep = self.sweep

    if arg == "status":
        await update.message.reply_text(status_text(sweep.status()), parse_mode=ParseMode.MARKDOWN)
        return

    if arg == "reviews":
        reviews = sweep.repo.pending_reviews()
        if not reviews:
            await update.message.reply_text("No pairs waiting for your ear.")
            return
        sent = await send_sweep_pairs(
            context.bot,
            update.effective_chat.id,
            reviews,
            mark_offered=lambda rid: sweep.repo.mark_offered(rid, time.time()),
        )
        await update.message.reply_text(f"Sent {sent} pair(s).")
        return

    if arg == "stop":
        if not sweep.running:
            await update.message.reply_text("No sweep is running.")
            return
        run = await sweep.abort()
        rid = run.id if run is not None else "?"
        await update.message.reply_text(
            f"🧹 Sweep {rid} stopped. `/sweep` or `/sweep force` starts a new one.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if arg and arg not in ("force",):
        await update.message.reply_text(_HELP, parse_mode=ParseMode.MARKDOWN)
        return

    run, why = sweep.start("telegram", force=arg == "force")
    if run is None:
        hint = ""
        if "already running" in why:
            hint = "\n\nUse `/sweep stop` first, then `/sweep force`."
        await update.message.reply_text(
            f"Not started: {escape_md(why)}.{hint}\n\n{status_text(sweep.status())}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await update.message.reply_text(
        f"🧹 Library sweep started (id {run.id}). `/sweep status` shows where it is.",
        parse_mode=ParseMode.MARKDOWN,
    )
