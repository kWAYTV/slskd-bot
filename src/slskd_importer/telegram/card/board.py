"""Keeps every batch's card message up to date: which view it shows, and throttled redraws."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import RetryAfter

from slskd_importer.queue.batch import SAVED_STATUSES, WAITING_STATUSES, Batch, BatchStatus, Item, ItemStatus
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
# Taps on copy buttons are ignored this long after another track came on screen.
TAP_GUARD_SECS = 0.6

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
    # Going through the tracks waiting for a pick: after each pick the next one's picker opens.
    tour: bool = False


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
        self._opened_at: dict[int, float] = {}

    def show(self, batch_id: int, view: View) -> None:
        self._views[batch_id] = view

    def view_of(self, batch_id: int) -> View:
        return self._views.get(batch_id, View())

    def focus(self, batch_id: int, kind: str, item_id: int, page: int = 0, *, tour: bool | None = None) -> None:
        """Show a track's item or picker view, remembering the summary or list page it was opened from.

        *tour* starts (True) or ends (False) going through the waiting tracks; None keeps it as it is
        while moving between a track's views, and ends it when the track is opened from elsewhere.
        """
        current = self.view_of(batch_id)
        if current.kind == LIST:
            back, back_page, touring = LIST, current.page, False
        elif current.kind == SUMMARY:
            back, back_page, touring = SUMMARY, 0, False
        else:
            back, back_page, touring = current.back, current.back_page, current.tour
        if current.item_id != item_id or current.kind not in (ITEM, PICKER):
            self._opened_at[batch_id] = time.monotonic()
        self._views[batch_id] = View(kind, item_id, page, back, back_page, touring if tour is None else tour)

    def just_opened(self, batch_id: int) -> bool:
        """True for a moment after another track came on screen.

        A second tap of a double tap lands where the first one was, which is now a button of
        the next track; such a tap must not pick a copy.
        """
        return time.monotonic() - self._opened_at.get(batch_id, 0.0) < TAP_GUARD_SECS

    def forget_drawn(self, batch_id: int) -> None:
        """Make the next draw edit the message even if the content did not change (the message is new)."""
        self._drawn.pop(batch_id, None)

    def leave(self, batch_id: int) -> None:
        """Go back to where the current track was opened from: done with it."""
        current = self.view_of(batch_id)
        self._views[batch_id] = View(current.back, page=current.back_page)

    @staticmethod
    def _origin(batch: Batch, view: View) -> str:
        """Callback data that returns to the view's origin."""
        if view.back == LIST:
            return actions.encode(actions.LIST, batch.id, 0, view.back_page)
        return actions.encode(actions.SUMMARY, batch.id)

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
                self.request(batch_id)  # a draw asked for by a tap has no redraw loop behind it
        await self._react_when_finished(batch, items)

    def compose(self, batch: Batch, items: list[Item]) -> Card:
        t = partial(translate, self._locale_of(batch.chat_id))
        progress = self._runner.progress
        view = self._views.get(batch.id, View())
        item = next((i for i in items if i.id == view.item_id), None)
        if view.kind == PICKER and item is not None:
            # Nothing remembered yet means the callback that opened the picker is still searching.
            copies = self._runner.pipeline.finder.remembered(item.id)
            # A track that only waits for a pick has no item view worth returning to.
            waiting = item.status == ItemStatus.choose and len(items) > 1
            back = self._origin(batch, view) if waiting else ""
            remaining = sum(1 for other in items if other.status == ItemStatus.choose) if view.tour else 0
            return render_picker(t, batch, item, copies, view.page, self._page_size, back=back, remaining=remaining)
        if len(items) == 1:
            only = items[0]
            copies = self._runner.pipeline.finder.remembered(only.id)
            if only.status == ItemStatus.choose and view.kind != ITEM and copies is not None:
                # A song asked for on its own opens straight on its copies.
                return render_picker(t, batch, only, copies, view.page, self._page_size)
            return render_item(t, batch, only, progress.get(only.id), alone=True)
        if view.kind == ITEM and item is not None:
            return render_item(t, batch, item, progress.get(item.id), alone=False, back=self._origin(batch, view))
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
        got = any(item.status in (*SAVED_STATUSES, ItemStatus.owned) for item in items)
        if not got and any(item.status in WAITING_STATUSES for item in items):
            return  # still waiting for the requester: the request keeps its 👀
        await react(self.telegram, batch.chat_id, batch.query_message_id, REACTION_SAVED if got else REACTION_NOTHING)
