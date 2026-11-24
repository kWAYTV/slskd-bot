"""Hand a track's file to the requester's chat.

Used two ways: as the queue's delivery step for people without library
access, and for the *Send file* button on a saved track.

Functions take the ``MusicBot`` instance as ``self`` and are bound as class
attributes in ``core.app``.
"""

from __future__ import annotations

import logging

from telegram.error import TelegramError, TimedOut

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.queue.batch import Batch, Item
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.telegram.delivery.send import Audio, send_file
from slskd_importer.telegram.ui.feedback import show_uploading

logger = logging.getLogger(__name__)


async def deliver_copy(
    self, batch: Batch, item: Item, track: TrackInfo, result: SearchResult, path: str, quality: str
) -> bool:
    """Queue delivery step: send a fetched copy to the batch's chat. True when it reached the chat."""
    filename = self.processor.build_filename(track.artist, track.title, result.extension)
    return await _send(self, batch, track, path, filename, quality)


async def send_saved_file(self, batch: Batch, item: Item) -> bool:
    """Send a track already saved in the library to the batch's chat."""
    track = item.track
    if track is None or not item.saved_name:
        return False
    return await _send(self, batch, track, self.shelf.path_of(item.saved_name), item.saved_name, item.quality)


async def _send(self, batch: Batch, track: TrackInfo, path: str, filename: str, quality: str) -> bool:
    chat_id = batch.chat_id
    limit = self.config.telegram_file_limit
    audio = Audio(
        filename=filename,
        title=track.title,
        performer=track.artist,
        duration=track.duration_secs,
        caption=f"{track.artist} — {track.title}\n{quality}".strip(),
    )
    await show_uploading(self.telegram, chat_id)
    try:
        return await send_file(
            self.telegram,
            chat_id,
            path,
            audio,
            file_limit=limit,
            oversize_note=self.t(chat_id, "oversize_note", limit=limit // (1024 * 1024)),
            reply_to=batch.message_id,
        )
    except TimedOut:
        # Large uploads often land on Telegram's side after the client gives up waiting.
        logger.warning("Telegram did not confirm %s in time; treating it as sent", filename)
        return True
    except (TelegramError, OSError):
        logger.exception("Sending %s to chat %s failed", filename, chat_id)
        return False
