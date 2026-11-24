"""Send an audio file to a chat: as audio, as a document when Telegram refuses, as OGG when it is too big."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
from dataclasses import dataclass

from telegram import Bot
from telegram.error import BadRequest, RetryAfter

from slskd_importer.library.preview import convert_to_ogg
from slskd_importer.telegram.ui.reply import reply_kwargs

logger = logging.getLogger(__name__)

# Local Bot API servers return flood control as a 400 ("retry after N"), not RetryAfter.
_RETRY_AFTER_RE = re.compile(r"retry after (\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class Audio:
    """What Telegram shows for a sent file."""

    filename: str
    title: str
    performer: str
    duration: int
    caption: str


def flood_wait_secs(exc: BaseException) -> float | None:
    """Seconds to wait before a second send, or None when this is not flood control."""
    if isinstance(exc, RetryAfter):
        wait = exc.retry_after
        return (wait.total_seconds() if hasattr(wait, "total_seconds") else float(wait)) + 0.5
    match = _RETRY_AFTER_RE.search(str(exc))
    return float(match.group(1)) + 0.5 if match else None


async def send_file(
    bot: Bot, chat_id: int, path: str, audio: Audio, *, file_limit: int, oversize_note: str, reply_to: int | None = None
) -> bool:
    """Send *path* to the chat. A file over *file_limit* goes as OGG Opus with *oversize_note* in its caption.

    Returns False when nothing could be sent (too big even as OGG, or the conversion failed).
    """
    if os.path.getsize(path) <= file_limit:
        await _send_audio_or_document(bot, chat_id, path, audio, reply_to)
        return True

    ogg_path = await asyncio.to_thread(convert_to_ogg, path)
    if ogg_path is None:
        return False
    try:
        if os.path.getsize(ogg_path) > file_limit:
            return False
        stem = os.path.splitext(audio.filename)[0]
        noted = Audio(f"{stem}.ogg", audio.title, audio.performer, audio.duration, f"{audio.caption}\n{oversize_note}")
        await _send_audio_or_document(bot, chat_id, ogg_path, noted, reply_to)
        return True
    finally:
        with contextlib.suppress(OSError):
            os.unlink(ogg_path)


async def _send_audio_or_document(bot: Bot, chat_id: int, path: str, audio: Audio, reply_to: int | None) -> None:
    """send_audio; on flood control wait and retry once; on any other refusal send as a document."""

    async def as_audio() -> None:
        with open(path, "rb") as handle:
            await bot.send_audio(
                chat_id=chat_id,
                audio=handle,
                filename=audio.filename,
                title=audio.title,
                performer=audio.performer,
                duration=audio.duration,
                caption=audio.caption,
                **reply_kwargs(reply_to),
            )

    try:
        await as_audio()
        return
    except (BadRequest, RetryAfter) as exc:
        wait = flood_wait_secs(exc)
        if wait is not None:
            logger.info("Telegram flood control: waiting %.1fs before sending %s again", wait, audio.filename)
            await asyncio.sleep(wait)
            with contextlib.suppress(BadRequest, RetryAfter):
                await as_audio()
                return
        logger.info("send_audio refused %s, sending as a document", audio.filename)

    with open(path, "rb") as handle:
        await bot.send_document(
            chat_id=chat_id,
            document=handle,
            filename=audio.filename,
            caption=audio.caption,
            **reply_kwargs(reply_to),
        )
