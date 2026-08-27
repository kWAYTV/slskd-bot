"""Advance the import job: pick the next pending track and start its search."""

from __future__ import annotations

import asyncio
import logging

from telegram.constants import ParseMode

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.playlist_import.job import TrackStatus
from slskd_importer.telegram.playlist_import.summary import send_import_summary
from slskd_importer.telegram.ui.editing import safe_edit
from slskd_importer.telegram.ui.markdown import escape_md

logger = logging.getLogger(__name__)


async def process_next_import_track(self, context, chat_id: int, job_id: int, generation: int):
    """Process the next pending track in an import job."""
    if self._is_stale(chat_id, generation):
        return

    while True:
        if self._is_stale(chat_id, generation):
            return

        next_track = await asyncio.to_thread(self.import_repo.get_next_pending_track, job_id)
        if not next_track:
            await send_import_summary(self, context, chat_id, job_id)
            return

        track_info = TrackInfo(
            artist=next_track.artist,
            title=next_track.title,
            album=next_track.album,
            duration_ms=next_track.duration_ms,
            spotify_url=next_track.spotify_url,
            year=next_track.year,
        )

        progress = await asyncio.to_thread(self.import_repo.get_job_progress, job_id)
        completed, failed, skipped, total = progress
        position = completed + failed + skipped + 1

        if await _already_owned(self, track_info):
            logger.info(
                "chat=%s import job %s skip owned %d/%d: %s - %s",
                chat_id,
                job_id,
                position,
                total,
                track_info.artist,
                track_info.title,
            )
            await asyncio.to_thread(
                self.import_repo.complete_track,
                job_id,
                next_track.id,
                TrackStatus.skipped,
                "Already in library",
            )
            await _edit_import_status(
                self,
                context,
                chat_id,
                self.t(
                    chat_id,
                    "import_owned",
                    position=position,
                    total=total,
                    artist=escape_md(track_info.artist),
                    title=escape_md(track_info.title),
                ),
            )
            continue

        logger.info(
            "chat=%s import job %s track %d/%d: %s - %s",
            chat_id,
            job_id,
            position,
            total,
            track_info.artist,
            track_info.title,
        )
        await asyncio.to_thread(self.import_repo.update_track_status, next_track.id, TrackStatus.searching)

        searching_msg = await _edit_import_status(
            self,
            context,
            chat_id,
            self.t(
                chat_id,
                "import_searching",
                position=position,
                total=total,
                artist=escape_md(track_info.artist),
                title=escape_md(track_info.title),
                album=escape_md(track_info.album),
                year=escape_md(track_info.year),
            ),
        )
        await self._do_import_slskd_search(
            context,
            chat_id,
            track_info,
            searching_msg,
            generation,
            job_id,
            next_track.id,
            position=position,
            total=total,
        )
        return


async def _already_owned(self, track: TrackInfo) -> bool:
    exact = self.processor.find_exact(track.artist, track.title)
    if exact:
        return True
    history_hit = await asyncio.to_thread(
        self.history_repo.find_success,
        track.artist,
        track.title,
        track.spotify_url,
    )
    return history_hit is not None


async def _edit_import_status(self, context, chat_id: int, text: str):
    """Edit the single in-place import progress message, or send one if missing."""
    msg = self._import_status_msg.get(chat_id)
    if msg is not None:
        if await safe_edit(msg, text, parse_mode=ParseMode.MARKDOWN):
            return msg
    sent = await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)
    self._import_status_msg[chat_id] = sent
    return sent
