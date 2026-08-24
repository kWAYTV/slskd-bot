"""End-of-import summary card with failed-track retry."""

from __future__ import annotations

import asyncio
import logging

from telegram.constants import ParseMode

from music_downloader.playlist_import.job import JobStatus
from music_downloader.telegram.ui.keyboards import build_import_summary_keyboard
from music_downloader.telegram.ui.markdown import escape_md

logger = logging.getLogger(__name__)


async def send_import_summary(self, context, chat_id: int, job_id: int):
    """Send the end-of-import summary card, listing failures with a retry button."""
    completed, failed, skipped, total = await asyncio.to_thread(self.import_repo.get_job_progress, job_id)
    logger.info(
        "chat=%s import job %s complete: saved=%d failed=%d skipped=%d total=%d",
        chat_id,
        job_id,
        completed,
        failed,
        skipped,
        total,
    )
    await asyncio.to_thread(self.import_repo.update_job_status, job_id, JobStatus.completed)
    self._active_import.pop(chat_id, None)
    self._import_status_msg.pop(chat_id, None)

    lines = [
        ("🏁 *Import complete!*") + "\n",
        (f"✅ Saved: {completed}\n❌ Failed: {failed}\n⏭ Skipped: {skipped}\n📊 Total: {total}"),
    ]

    reply_markup = None
    if failed:
        failed_tracks = await asyncio.to_thread(self.import_repo.get_failed_tracks, job_id)
        if failed_tracks:
            lines.append("\n" + ("*Failed tracks:*"))
            for t in failed_tracks[:5]:
                lines.append(f"• {escape_md(t.artist)} - {escape_md(t.title)}")
            if len(failed_tracks) > 5:
                lines.append(f"…and {len(failed_tracks) - 5} more")
            reply_markup = build_import_summary_keyboard(job_id, len(failed_tracks))

    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
    )
