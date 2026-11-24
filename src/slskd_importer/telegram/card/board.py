"""Keeps every batch's card message up to date: which view it shows, and throttled redraws."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import RetryAfter

from slskd_importer.queue.batch import Batch, BatchStatus, Item, ItemStatus
from slskd_importer.queue.runner import QueueRunner
from slskd_importer.telegram.card import actions
from slskd_importer.telegram.card.item_view import Card, render_item
from slskd_importer.telegram.card.list_view import render_list
from slskd_importer.telegram.card.picker_view import render_picker
from slskd_importer.telegram.card.summary_view import render_summary
from slskd_importer.telegram.i18n import t as translate
from slskd_importer.telegram.ui.editing import safe_bot_edit
from slskd_importer.telegram.ui.feedback import REACTION_NOTHING, REACTION_SAVED, react

logger = logging.getLogger(__name__)

# Telegram allows about one edit a second per chat; several cards may share a chat.
REDRAW_INTERVAL_SECS = 2.5

SUMMARY = "summary"
LIST = "list"
ITEM = "item"
PICKER = "picker"


@dataclass(frozen=True)
class View:
    """What a card shows. *back* / *back_page*: where a track was opened from (summary, or a list page)."""

    kind: str = SUMMARY
    item_id: int = 0
    page: int = 0
    back: str = SUMMARY
    back_page: int = 0


class CardBoard:
    def __init__(self, runner: QueueRunner, locale_of: Callable[[int], str], page_size: int) -> None:
        self._runner = runner
        self._store = runner.store
        self._locale_of = locale_of
        self._page_size = page_size
        self.telegram: Bot | None = None
        self._views: dict[int, View] = {}
        self._drawn: dict[int, tuple[str, dict | None]] = {}
        self._redraws: dict[int, asyncio.Task] = {}
        self._dirty: set[int] = set()
        self._reacted: set[int] = set()

    def show(self, batch_id: int, view: View) -> None:
        self._views[batch_id] = view

    def focus(self, batch_id: int, kind: str, item_id: int, page: int = 0) -> None:
        """Show a track's item or picker view, remembering where the track was opened from."""
        current = self._views.get(batch_id, View())
        self._views[batch_id] = View(kind, item_id, page, current.back, current.back_page)

    def request(self, batch_id: int) -> None:
        """Redraw the batch's card soon. Calls while a redraw is cooling down collapse into one."""
        if batch_id in self._redraws:
            self._dirty.add(batch_id)
            return
        self._redraws[batch_id] = asyncio.get_running_loop().create_task(self._redraw_loop(batch_id))

    async def _redraw_loop(self, batch_id: int) -> None:
        try:
            while True:
                self._dirty.discard(batch_id)
                await self.draw(batch_id)
                await asyncio.sleep(REDRAW_INTERVAL_SECS)
                if batch_id not in self._dirty:
                    return
        except Exception:
            logger.exception("Redrawing the card of batch %d failed", batch_id)
        finally:
            self._redraws.pop(batch_id, None)

    async def draw(self, batch_id: int) -> None:
        """Render the card and edit its message when the content changed."""
        batch = await asyncio.to_thread(self._store.get_batch, batch_id)
        if batch is None or batch.message_id is None or self.telegram is None:
            return
        items = await asyncio.to_thread(self._store.items, batch_id)
        text, markup = self.compose(batch, items)
        drawn = (text, markup.to_dict() if markup else None)
        if self._drawn.get(batch_id) != drawn:
            try:
                edited = await safe_bot_edit(
                    self.telegram,
                    batch.chat_id,
                    batch.message_id,
                    text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=markup,
                    disable_web_page_preview=True,
                )
                if edited:
                    self._drawn[batch_id] = drawn
            except RetryAfter as exc:
                logger.info("Telegram flood control on batch %d: waiting %ss", batch_id, exc.retry_after)
                self._dirty.add(batch_id)
                wait = exc.retry_after
                await asyncio.sleep(wait.total_seconds() if hasattr(wait, "total_seconds") else float(wait))
        await self._react_when_finished(batch, items)

    def compose(self, batch: Batch, items: list[Item]) -> Card:
        t = partial(translate, self._locale_of(batch.chat_id))
        progress = self._runner.progress
        view = self._views.get(batch.id, View())
        item = next((i for i in items if i.id == view.item_id), None)
        if view.kind == PICKER and item is not None:
            # Nothing remembered yet means the callback that opened the picker is still searching.
            copies = self._runner.pipeline.finder.remembered(item.id)
            return render_picker(t, batch, item, copies, view.page, self._page_size)
        if len(items) == 1:
            only = items[0]
            copies = self._runner.pipeline.finder.remembered(only.id)
            if only.status == ItemStatus.choose and view.kind != ITEM and copies is not None:
                # A song asked for on its own opens straight on its copies.
                return render_picker(t, batch, only, copies, view.page, self._page_size)
            return render_item(t, batch, only, progress.get(only.id), alone=True)
        if view.kind == ITEM and item is not None:
            back = (
                actions.encode(actions.LIST, batch.id, 0, view.back_page)
                if view.back == LIST
                else actions.encode(actions.SUMMARY, batch.id)
            )
            return render_item(t, batch, item, progress.get(item.id), alone=False, back=back)
        if view.kind == LIST:
            return render_list(t, batch, items, progress, view.page)
        return render_summary(t, batch, items, progress)

    async def _react_when_finished(self, batch: Batch, items: list[Item]) -> None:
        """The requester's own message says how it ended: 👍 something arrived, 🤷 nothing did."""
        if batch.status == BatchStatus.active:
            self._reacted.discard(batch.id)
        if batch.status != BatchStatus.done or batch.id in self._reacted:
            return
        self._reacted.add(batch.id)
        got = any(item.status in (ItemStatus.done, ItemStatus.owned) for item in items)
        if not got and any(item.status in (ItemStatus.choose, ItemStatus.review) for item in items):
            return  # still waiting for the requester: the request keeps its 👀
        await react(self.telegram, batch.chat_id, batch.query_message_id, REACTION_SAVED if got else REACTION_NOTHING)
