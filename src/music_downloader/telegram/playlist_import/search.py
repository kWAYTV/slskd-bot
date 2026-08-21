"""Per-track Soulseek search inside an import job (same fallbacks as manual search)."""

from __future__ import annotations

import asyncio
import logging

from telegram.constants import ParseMode

from music_downloader.catalog.track import TrackInfo
from music_downloader.playlist_import.job import TrackStatus
from music_downloader.soulseek.errors import SlskdUnavailableError
from music_downloader.soulseek.query import clean_search_title
from music_downloader.telegram.core.session import PendingDownload, PendingSearch
from music_downloader.telegram.ui.editing import safe_edit
from music_downloader.telegram.ui.keyboards import build_import_skip_keyboard
from music_downloader.telegram.ui.markdown import escape_md, md_code_safe

logger = logging.getLogger(__name__)


async def do_import_slskd_search(
    self, context, chat_id: int, track: TrackInfo, searching_msg, generation: int, job_id: int, track_id: int
):
    """Search slskd for an import track using the same four-tier fallbacks as manual search."""
    try:
        search_query = f"{track.artist} {clean_search_title(track.title)}"
        ranked, is_fallback, stale = await self._search_with_fallbacks(track, chat_id, generation)
        if stale:
            return

        if not ranked:
            await safe_edit(
                searching_msg,
                (
                    f"📋 *Import track:* {escape_md(track.artist)} - {escape_md(track.title)}\n\nNo results found on Soulseek."
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_import_skip_keyboard(job_id, track_id),
            )
            await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.awaiting_approval)
            return

        best = ranked[0]

        self._import_pending[chat_id] = PendingSearch(
            query=search_query,
            track=track,
            results=ranked,
            message_id=searching_msg.message_id,
            is_fallback=is_fallback,
        )

        dl_id = self._next_dl_id()
        pending_dl = PendingDownload(
            track=track,
            result=best,
            chat_id=chat_id,
            source_path=None,
            status_message_id=searching_msg.message_id,
        )
        self.downloads[dl_id] = pending_dl

        await safe_edit(
            searching_msg,
            (
                f"📋 *Import track:* {escape_md(track.artist)} - {escape_md(track.title)}\n⬇️ Downloading: `{md_code_safe(best.basename)}`\nFrom: `{md_code_safe(best.username)}` | {best.quality_display}"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

        task = context.application.create_task(
            self._do_import_download(context, chat_id, track, best, searching_msg, generation, job_id, track_id, dl_id),
            update=None,
        )
        self._track_task(chat_id, task)

    except SlskdUnavailableError:
        logger.exception("slskd unreachable during import search for: %s - %s", track.artist, track.title)
        await safe_edit(
            searching_msg,
            ("Cannot reach slskd. Check `SLSKD_HOST` and the API key."),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_import_skip_keyboard(job_id, track_id),
        )
        await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.awaiting_approval)
    except Exception:
        logger.exception(f"Import search failed for: {track.artist} - {track.title}")
        await safe_edit(
            searching_msg,
            (f"❌ Search failed for {track.artist} - {track.title}"),
        )
        await asyncio.to_thread(self.import_repo.complete_track, job_id, track_id, TrackStatus.failed, "Search error")
        await self._process_next_import_track(context, chat_id, job_id, generation)
