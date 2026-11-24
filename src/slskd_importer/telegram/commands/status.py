"""/status: the chat's batches that are working or waiting for a decision, and a way to bring a card back down."""

from __future__ import annotations

import asyncio
import logging
from functools import partial

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.queue.batch import OPEN_STATUSES, WAITING_STATUSES, Batch, BatchStatus, ItemStatus
from slskd_importer.telegram.card.board import View
from slskd_importer.telegram.i18n import t as translate
from slskd_importer.telegram.ui.editing import safe_bot_edit
from slskd_importer.telegram.ui.formatting import clip
from slskd_importer.telegram.ui.markdown import escape_md

logger = logging.getLogger(__name__)

# Callback data of a "bring this card here" button: ``sb:<batch id>``.
BRING_PREFIX = "sb"


def _name(t, batch: Batch, total: int) -> str:
    return t("list_name", n=total) if batch.kind == "list" else batch.name


async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await self._check_auth(update):
        return

    chat_id = update.effective_chat.id
    t = partial(translate, self.locale(chat_id))
    batches = await asyncio.to_thread(self.queue_store.open_batches, chat_id)
    if not batches:
        await update.message.reply_text(t("status_empty"))
        return

    lines = [t("status_header"), ""]
    buttons = []
    for batch in batches:
        counts = await asyncio.to_thread(self.queue_store.counts, batch.id)
        total = sum(counts.values())
        name = _name(t, batch, total)
        lines.append(f"• {escape_md(name)}  ·  {_standing(t, counts, total)}")
        buttons.append([InlineKeyboardButton(clip(f"📍 {name}"), callback_data=f"{BRING_PREFIX}:{batch.id}")])
    lines += ["", t("status_bring_hint")]
    if any(batch.status == BatchStatus.active for batch in batches):
        buttons.append([InlineKeyboardButton(t("btn_cancel_all"), callback_data="cancel_all")])

    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons)
    )


def _standing(t, counts: dict[str, int], total: int) -> str:
    in_flight = sum(counts.get(status, 0) for status in OPEN_STATUSES)
    parts = [f"{total - in_flight} / {total}"] if in_flight else []
    to_pick = counts.get(ItemStatus.choose, 0)
    if to_pick:
        parts.append(t("count_choose", n=to_pick))
    to_review = sum(counts.get(status, 0) for status in (*WAITING_STATUSES, ItemStatus.doubt)) - to_pick
    if to_review:
        parts.append(t("count_review", n=to_review))
    return "  ·  ".join(parts)


async def handle_bring_card(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, data: str):
    """A 📍 button under /status: post the batch's card again at the bottom of the chat.

    A card scrolls away while a long list is being worked through; Telegram
    cannot move a message, so a new one takes over and the old one says so.
    """
    try:
        batch_id = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return
    batch = await asyncio.to_thread(self.queue_store.get_batch_for_chat, batch_id, chat_id)
    if batch is None:
        return
    fresh = await context.bot.send_message(chat_id=chat_id, text=self.t(chat_id, "intake_reading"))
    await asyncio.to_thread(self.queue_store.set_message, batch.id, fresh.message_id)
    logger.info("chat=%s batch %d: card moved to message %s", chat_id, batch.id, fresh.message_id)
    if batch.message_id:
        await safe_bot_edit(context.bot, chat_id, batch.message_id, self.t(chat_id, "card_moved"))
    self.cards.forget_drawn(batch.id)
    self.cards.show(batch.id, View())
    await self.cards.draw(batch.id)
