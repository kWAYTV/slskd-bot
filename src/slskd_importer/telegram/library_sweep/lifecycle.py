"""Start/stop the library sweep schedule loop (TTL-style)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from telegram.ext import Application

from slskd_importer.sweep.outcomes import SweepReport
from slskd_importer.telegram.library_sweep.pairs import send_sweep_pairs
from slskd_importer.telegram.library_sweep.report import report_caption

logger = logging.getLogger(__name__)

_TASK_KEY = "library_sweep_schedule_task"


async def _on_report(application: Application, bot, report: SweepReport) -> None:
    users = bot.sweep.users
    caption = report_caption(report)
    for user_id in users:
        try:
            await application.bot.send_message(chat_id=user_id, text=caption, parse_mode="Markdown")
            if not report.in_progress and report.reviews:
                await send_sweep_pairs(
                    application.bot,
                    user_id,
                    report.reviews,
                    mark_offered=lambda rid: bot.sweep.repo.mark_offered(rid, time.time()),
                )
        except Exception:
            logger.exception("Sweep report to user %s failed", user_id)


def start_library_sweep(bot, application: Application) -> None:
    """Wire on_report, resume interrupted runs, start the schedule loop."""
    if not bot.sweep.enabled:
        logger.info("Library sweep schedule not started (no allowed/library users)")
        return

    async def on_report(report: SweepReport) -> None:
        await _on_report(application, bot, report)

    bot.sweep.on_report = on_report

    async def _run() -> None:
        try:
            await bot.sweep.schedule_loop()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Library sweep schedule loop crashed")

    loop = asyncio.get_running_loop()
    application.bot_data[_TASK_KEY] = loop.create_task(_run(), name="library-sweep-schedule")
    logger.info("Library sweep schedule loop started")


async def stop_library_sweep(application: Application) -> None:
    task = application.bot_data.pop(_TASK_KEY, None)
    bot = application.bot_data.get("music_bot")
    if bot is not None:
        await bot.sweep.stop()
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
