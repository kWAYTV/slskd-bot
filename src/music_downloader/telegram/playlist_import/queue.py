"""Advance the import job: pick the next pending track and start its search."""

from __future__ import annotations

import asyncio

from telegram.constants import ParseMode

from music_downloader.catalog.track import TrackInfo
from music_downloader.playlist_import.job import TrackStatus
from music_downloader.telegram.playlist_import.summary import send_import_summary
from music_downloader.telegram.ui.markdown import escape_md


async def process_next_import_track(self, context, chat_id: int, job_id: int, generation: int):
    """Process the next pending track in an import job."""
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

    await asyncio.to_thread(self.import_repo.update_track_status, next_track.id, TrackStatus.searching)

    searching_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"📋 *Import [{position}/{total}]*\n🔍 Searching: *{escape_md(track_info.artist)} - {escape_md(track_info.title)}*\nAlbum: {escape_md(track_info.album)} ({escape_md(track_info.year)})"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )

    await self._do_import_slskd_search(context, chat_id, track_info, searching_msg, generation, job_id, next_track.id)
