"""Safe Telegram message edits that swallow transient API failures."""

import contextlib
import logging

from telegram import Message
from telegram.constants import ParseMode
from telegram.error import BadRequest, NetworkError, TimedOut

logger = logging.getLogger(__name__)


async def safe_edit(msg: Message, text: str, **kwargs) -> bool:
    """Edit a Telegram message, swallowing common failures.

    Returns True on success, False if the edit failed (logged as warning).
    """
    try:
        await msg.edit_text(text, **kwargs)
        return True
    except BadRequest as exc:
        logger.warning(f"Telegram edit failed (BadRequest): {exc}")
        return False
    except TimedOut:
        logger.warning("Telegram edit timed out")
        return False
    except NetworkError as exc:
        logger.warning(f"Telegram edit network error: {exc}")
        return False


async def safe_query_edit(query, text: str, **kwargs) -> bool:
    """Edit a callback query message, swallowing transient Telegram errors."""
    try:
        await query.edit_message_text(text, **kwargs)
        return True
    except BadRequest as exc:
        logger.warning(f"Telegram query edit failed (BadRequest): {exc}")
        return False
    except TimedOut:
        logger.warning("Telegram query edit timed out")
        return False
    except NetworkError as exc:
        logger.warning(f"Telegram query edit network error: {exc}")
        return False


async def edit_approval_message(query, text: str):
    """Edit the approval message — works for both audio captions and text messages."""
    try:
        await query.edit_message_caption(caption=text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        with contextlib.suppress(Exception):
            await query.edit_message_text(text=text, parse_mode=ParseMode.MARKDOWN)
