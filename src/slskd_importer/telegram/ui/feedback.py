"""Low-noise feedback through Telegram itself: reactions, chat actions, pins.

Every helper swallows API errors: feedback must never break a flow.
"""

from __future__ import annotations

import contextlib
import logging

from telegram import ReactionTypeEmoji
from telegram.constants import ChatAction

logger = logging.getLogger(__name__)

# Telegram only accepts its fixed reaction set; ✅ is not in it.
REACTION_SEARCHING = "👀"
REACTION_SAVED = "👍"
REACTION_NOTHING = "🤷"
REACTION_FAILED = "👎"


async def react(bot, chat_id: int, message_id: int | None, emoji: str | None) -> None:
    """Set (or with ``None`` clear) the bot's reaction on a message."""
    if not message_id:
        return
    with contextlib.suppress(Exception):
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji)] if emoji else [],
        )


async def show_typing(bot, chat_id: int) -> None:
    """'typing…' in the chat header while a lookup or search runs."""
    with contextlib.suppress(Exception):
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)


async def show_uploading(bot, chat_id: int) -> None:
    """'sending file…' in the chat header while a preview uploads."""
    with contextlib.suppress(Exception):
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)


async def pin(bot, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    with contextlib.suppress(Exception):
        await bot.pin_chat_message(chat_id=chat_id, message_id=message_id, disable_notification=True)


async def unpin(bot, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    with contextlib.suppress(Exception):
        await bot.unpin_chat_message(chat_id=chat_id, message_id=message_id)
