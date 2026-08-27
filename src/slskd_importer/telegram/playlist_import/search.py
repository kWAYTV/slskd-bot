"""Per-track Soulseek search inside an import job (same fallbacks as manual search)."""

from __future__ import annotations

import asyncio
import logging

from telegram.constants import ParseMode

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.playlist_import.job import TrackStatus
from slskd_importer.soulseek.errors import SlskdUnavailableError
from slskd_importer.soulseek.query import clean_search_title
from slskd_importer.telegram.core.session import PendingDownload, PendingSearch
from slskd_importer.telegram.playlist_import.keyboards import build_import_skip_keyboard
from slskd_importer.telegram.ui.editing import safe_edit
from slskd_importer.telegram.ui.markdown import escape_md, md_code_safe

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
                self.t(chat_id, "import_no_results", artist=escape_md(track.artist), title=escape_md(track.title)),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_import_skip_keyboard(job_id, track_id, locale=self.locale(chat_id)),
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
                self.t(
                    chat_id,
                    "import_downloading",
                    artist=escape_md(track.artist),
                    title=escape_md(track.title),
                    file=md_code_safe(best.basename),
                    user=md_code_safe(best.username),
                    quality=best.quality_display,
                )
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
            self.t(chat_id, "slskd_unreachable"),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_import_skip_keyboard(job_id, track_id, locale=self.locale(chat_id)),
        )
        await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.awaiting_approval)
    except Exception:
        logger.exception(f"Import search failed for: {track.artist} - {track.title}")
        await safe_edit(
            searching_msg,
            self.t(chat_id, "import_search_failed", artist=track.artist, title=track.title),
        )
        await asyncio.to_thread(self.import_repo.complete_track, job_id, track_id, TrackStatus.failed, "Search error")
        await self._process_next_import_track(context, chat_id, job_id, generation)
