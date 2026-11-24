"""A chat message becomes a queue batch with one card.

Song names, one per line, and links (Spotify, YouTube, SoundCloud, Bandcamp,
tracklist pages) are all accepted, mixed freely. People with library access
get their tracks saved; everyone else gets the files sent to the chat.

Functions take the ``MusicBot`` instance as ``self`` and are bound as class
attributes in ``core.app``.
"""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from slskd_importer.queue.batch import Destination
from slskd_importer.sources.message import read_message
from slskd_importer.sources.tracklist import SourceError
from slskd_importer.telegram.ui.editing import safe_edit
from slskd_importer.telegram.ui.feedback import REACTION_NOTHING, REACTION_SEARCHING, react, show_typing
from slskd_importer.telegram.ui.reply import reply_kwargs

logger = logging.getLogger(__name__)


async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Free text: queue whatever the message asks for."""
    if not await self._check_auth(update):
        return
    await _queue_text(self, update, context, update.message.text or "")


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
