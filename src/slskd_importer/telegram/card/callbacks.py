"""Card buttons: navigation between views and batch-wide actions.

Functions take the ``MusicBot`` instance as ``self`` and are bound as class
attributes in ``core.app``.
"""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from slskd_importer.telegram.card import actions, board
from slskd_importer.telegram.card.board import View
from slskd_importer.telegram.card.track_actions import TRACK_ACTIONS

logger = logging.getLogger(__name__)


async def handle_card_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, data: str):
    """Route a ``q:`` callback to the view change or action it names."""
    action = actions.decode(data)
    if action is None:
        return
    batch = await asyncio.to_thread(self.queue_store.get_batch_for_chat, action.batch_id, chat_id)
    if batch is None:
        return
    logger.debug("chat=%s card action %s", chat_id, action)

    if action.name == actions.CANCEL:
        await self.runner.cancel_batch(batch.id)
    elif action.name == actions.RETRY_FAILED:
        await self.runner.retry_failed(batch.id)
        self.cards.show(batch.id, View(board.SUMMARY))
    elif action.name == actions.SUMMARY:
        self.cards.show(batch.id, View(board.SUMMARY))
    elif action.name == actions.LIST:
        self.cards.show(batch.id, View(board.LIST, page=action.number))
    elif action.name == actions.ITEM:
        self.cards.show(batch.id, View(board.ITEM, item_id=action.item_id))
    elif action.name in TRACK_ACTIONS:
        item = await asyncio.to_thread(self.queue_store.get_item, action.item_id)
        if item is None or item.batch_id != batch.id:
            return
        await TRACK_ACTIONS[action.name](self, update.callback_query, batch, item, action.number)
    await self.cards.draw(batch.id)
