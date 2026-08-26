"""Resume persisted import jobs after a restart or /import resume."""

from __future__ import annotations

import asyncio
import logging

from telegram.constants import ParseMode

from slskd_importer.playlist_import.job import JobStatus
from slskd_importer.telegram.ui.markdown import escape_md

logger = logging.getLogger(__name__)


class _ResumeContext:
    """Minimal context so import resume can use Application.bot."""

    def __init__(self, application):
        self.application = application
        self.bot = application.bot


async def resume_stale_imports(self, application) -> None:
    """Reset in-flight tracks and continue active import jobs after restart."""
    jobs = await asyncio.to_thread(self.import_repo.list_resumable_jobs)
    active_jobs = [job for job in jobs if job.status in (JobStatus.active, JobStatus.active.value)]
    if not active_jobs:
        return
    logger.info("Resuming %d import job(s)", len(active_jobs))
    ctx = _ResumeContext(application)
    for job in active_jobs:
        await resume_import_job(self, ctx, job.chat_id, notify=True, job=job)


async def resume_import_job(self, context, chat_id: int, notify: bool = False, job=None) -> None:
    """Continue a persisted import job in its original chat."""
    if job is None:
        job = await asyncio.to_thread(self.import_repo.get_active_job, chat_id)
    if not job:
        if notify:
            await context.bot.send_message(chat_id=chat_id, text=self.t(chat_id, "import_resume_nothing"))
        return

    if self._active_import.get(chat_id) == job.id:
        if notify:
            await context.bot.send_message(
                chat_id=chat_id,
                text=self.t(chat_id, "import_already_running", name=escape_md(job.name)),
                parse_mode=ParseMode.MARKDOWN,
            )
        return

    reset = await asyncio.to_thread(self.import_repo.reset_in_flight_tracks, job.id)
    if reset:
        logger.info("Reset %d in-flight track(s) for job %s", reset, job.id)

    if job.status in (JobStatus.pending, JobStatus.pending.value):
        await asyncio.to_thread(self.import_repo.update_job_status, job.id, JobStatus.active)

    self._active_import[chat_id] = job.id
    generation = self._chat_generation.get(chat_id, 0)
    remaining = job.total_tracks - job.completed_tracks - job.skipped_tracks - job.failed_tracks
    if notify:
        try:
            progress_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    self.t(
                        chat_id,
                        "import_resuming",
                        name=escape_md(job.name),
                        remaining=remaining,
                        done=job.completed_tracks,
                    )
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            self._import_status_msg[chat_id] = progress_msg
        except Exception:
            logger.warning("Could not notify chat %s about import resume", chat_id)

    task = asyncio.create_task(
        self._process_next_import_track(context, chat_id, job.id, generation),
    )
    self._track_task(chat_id, task)
