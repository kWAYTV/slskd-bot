"""Safe Telegram message edits that swallow transient API failures."""

import logging

from telegram import Message
from telegram.error import BadRequest, NetworkError, TimedOut

logger = logging.getLogger(__name__)


def _is_entity_parse_error(exc: BadRequest) -> bool:
    return "can't parse entities" in str(exc).lower()


async def _edit_text(edit, text: str, **kwargs) -> bool:
    """Run a Telegram text edit, retrying without parse_mode on Markdown errors."""
    try:
        await edit(text, **kwargs)
        return True
    except BadRequest as exc:
        if _is_entity_parse_error(exc) and kwargs.get("parse_mode"):
            logger.warning("Telegram edit failed (BadRequest): %s — retrying without parse_mode", exc)
            kwargs = {**kwargs, "parse_mode": None}
            try:
                await edit(text, **kwargs)
                return True
            except BadRequest as retry_exc:
                logger.warning("Telegram edit failed (BadRequest): %s", retry_exc)
                return False
        if "message is not modified" in str(exc).lower():
            return True
        logger.warning("Telegram edit failed (BadRequest): %s", exc)
        return False
    except TimedOut:
        logger.warning("Telegram edit timed out")
        return False
    except NetworkError as exc:
        logger.warning("Telegram edit network error: %s", exc)
        return False


async def safe_edit(msg: Message, text: str, **kwargs) -> bool:
    """Edit a Telegram message, swallowing common failures.

    Returns True on success, False if the edit failed (logged as warning).
    Entity-parse errors retry once without parse_mode so the user still sees results.
    """
    return await _edit_text(msg.edit_text, text, **kwargs)


async def safe_bot_edit(bot, chat_id: int, message_id: int, text: str, **kwargs) -> bool:
    """Edit a message known only by its ids (a card redrawn outside any update)."""

    async def edit(new_text: str, **edit_kwargs) -> None:
        await bot.edit_message_text(new_text, chat_id=chat_id, message_id=message_id, **edit_kwargs)

    return await _edit_text(edit, text, **kwargs)


async def safe_query_edit(query, text: str, **kwargs) -> bool:
    """Edit a callback query message, swallowing transient Telegram errors."""
    return await _edit_text(query.edit_message_text, text, **kwargs)
