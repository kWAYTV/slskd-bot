"""Reply-to helper so a card nests under the message that asked for it."""

from __future__ import annotations

from telegram import ReplyParameters


def reply_kwargs(message_id: int | None) -> dict:
    """Kwargs that make a send_* call quote ``message_id``. Empty if missing."""
    if not message_id:
        return {}
    return {"reply_parameters": ReplyParameters(message_id=message_id, allow_sending_without_reply=True)}
