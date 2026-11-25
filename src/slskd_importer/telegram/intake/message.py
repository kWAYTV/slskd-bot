"""A chat message becomes a queue batch with one card.

Song names, one per line, and links (Spotify, YouTube, SoundCloud, Bandcamp,
tracklist pages) are all accepted, mixed freely. People with library access
get their tracks saved; everyone else gets the files sent to the chat.

Functions take the ``MusicBot`` instance as ``self`` and are bound as class
attributes in ``core.app``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from slskd_importer.queue.batch import OPEN_STATUSES, Destination
from slskd_importer.sources.message import read_message
from slskd_importer.sources.text import clean_line
from slskd_importer.sources.tracklist import SourceError
from slskd_importer.telegram.card import board
from slskd_importer.telegram.ui.editing import safe_edit
from slskd_importer.telegram.ui.feedback import REACTION_NOTHING, REACTION_SEARCHING, react, show_typing
from slskd_importer.telegram.ui.reply import reply_kwargs

logger = logging.getLogger(__name__)


async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Free text: queue whatever the message asks for."""
    if not await self._check_auth(update):
        return
    if await _corrects_a_track(self, update, context):
        return
    await _queue_text(self, update, context, update.message.text or "")


async def _corrects_a_track(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """A reply to a batch card renames the track on it: ``Artist - Title`` for the song that was meant.

    True when the message was such a reply (handled here), False for an ordinary request.
    """
    replied_to = getattr(update.message.reply_to_message, "message_id", None)
    if not isinstance(replied_to, int):
        return False
    chat_id = update.effective_chat.id
    batch = await asyncio.to_thread(self.queue_store.batch_of_message, chat_id, replied_to)
    if batch is None:
        return False
    name = next((line for line in map(clean_line, (update.message.text or "").splitlines()) if line), "")
    if not name:
        return True

    items = await asyncio.to_thread(self.queue_store.items, batch.id)
    view = self.cards.view_of(batch.id)
    if len(items) == 1:
        item = items[0]
    else:
        on_screen = view.kind in (board.ITEM, board.PICKER)
        item = next((i for i in items if i.id == view.item_id), None) if on_screen else None
    if item is None:
        await update.message.reply_text(self.t(chat_id, "fix_open_track"))
        return True
    if item.status in OPEN_STATUSES:
        await update.message.reply_text(self.t(chat_id, "fix_busy"))
        return True

    logger.info("chat=%s item %d renamed: %r -> %r", chat_id, item.id, item.label, name)
    await self.runner.rename(item, name)
    self.cards.focus(batch.id, board.PICKER, item.id)  # "searching", then the copies of the right song
    await self.cards.draw(batch.id)
    with contextlib.suppress(TelegramError):
        await update.message.delete()  # the card now says it; keep the chat to cards
    return True


async def cmd_get(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """``/get <names or links>`` (also ``/import``): same as sending the text on its own."""
    if not await self._check_auth(update):
        return
    text = (update.message.text or "").split(maxsplit=1)
    if len(text) < 2:
        await update.message.reply_text(self.t(update.effective_chat.id, "get_usage"))
        return
    await _queue_text(self, update, context, text[1])


async def _queue_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    text = text.strip()
    if not text:
        return
    chat_id = update.effective_chat.id
    query_message_id = update.message.message_id

    await react(context.bot, chat_id, query_message_id, REACTION_SEARCHING)
    await show_typing(context.bot, chat_id)
    card = await context.bot.send_message(
        chat_id=chat_id, text=self.t(chat_id, "intake_reading"), **reply_kwargs(query_message_id)
    )
    # Resolving a playlist or a page can take a while; never block the next update on it.
    context.application.create_task(
        _resolve_and_queue(self, context, chat_id, update.effective_user.id, text, card, query_message_id),
        update=update,
    )


async def _resolve_and_queue(self, context, chat_id: int, user_id: int, text: str, card, query_message_id: int) -> None:
    try:
        tracklist = await asyncio.to_thread(read_message, text, self.spotify)
    except SourceError as exc:
        logger.info("chat=%s nothing to queue: %s", chat_id, exc)
        await safe_edit(card, str(exc))
        await react(context.bot, chat_id, query_message_id, REACTION_NOTHING)
        return
    except Exception:
        logger.exception("chat=%s reading a message failed", chat_id)
        await safe_edit(card, self.t(chat_id, "something_wrong"))
        await react(context.bot, chat_id, query_message_id, REACTION_NOTHING)
        return

    destination = Destination.library if self._can_save_library(user_id) else Destination.deliver
    batch = await asyncio.to_thread(
        self.queue_store.create_batch,
        chat_id,
        user_id,
        tracklist.name,
        tracklist.kind,
        tracklist.entries,
        source_url=tracklist.url,
        destination=destination,
        message_id=card.message_id,
        query_message_id=query_message_id,
    )
    logger.info(
        "chat=%s user=%s queued batch %d (%s, %d track(s), %s): %s",
        chat_id,
        user_id,
        batch.id,
        tracklist.kind,
        len(tracklist.entries),
        destination,
        tracklist.name,
    )
    await self.cards.draw(batch.id)
    self.runner.wake()
