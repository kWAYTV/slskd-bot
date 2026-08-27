"""Reply-to helpers so related messages visually nest under one parent card."""

from __future__ import annotations

import contextlib
import logging

from telegram import ReplyParameters

logger = logging.getLogger(__name__)


def reply_kwargs(message_id: int | None) -> dict:
    """Kwargs that make a send_* call quote ``message_id``. Empty if missing."""
    if not message_id:
        return {}
    return {"reply_parameters": ReplyParameters(message_id=message_id, allow_sending_without_reply=True)}


async def collapse_status_message(bot, chat_id: int, message_id: int | None, fallback: str | None = None) -> None:
    """Delete a progress text message after the preview lands.

    Falls back to a one-liner edit when delete is refused (e.g. old message).
    """
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        logger.debug("Could not delete status message %s", message_id, exc_info=True)
        if fallback:
            with contextlib.suppress(Exception):
                await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=fallback)
