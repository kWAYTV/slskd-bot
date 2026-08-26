"""Expire stale awaiting-approval downloads and delete leftover files."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

logger = logging.getLogger(__name__)

_SWEEP_INTERVAL_SECS = 900
_TTL_TASK_KEY = "approval_ttl_task"


def start_approval_ttl(self, application) -> None:
    """Schedule the sweep on the running event loop. Safe from ``post_init``."""
    application.bot_data[_TTL_TASK_KEY] = asyncio.create_task(
        run_approval_ttl_loop(self, application),
        name="approval-ttl",
    )


async def stop_approval_ttl(application) -> None:
    task = application.bot_data.pop(_TTL_TASK_KEY, None)
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def run_approval_ttl_loop(self, application) -> None:
    """Background loop: expire approvals older than ``approval_ttl_secs``."""
    while True:
        await asyncio.sleep(_SWEEP_INTERVAL_SECS)
        try:
            await expire_stale_approvals(self, application)
        except Exception:
            logger.exception("Approval TTL sweep failed")


async def expire_stale_approvals(self, application) -> None:
    ttl = self.config.approval_ttl_secs
    now = time.time()
    stale = [
        (dl_id, dl) for dl_id, dl in list(self.downloads.items()) if dl.source_path and (now - dl.created_at) >= ttl
    ]
    if not stale:
        return

    logger.info("Expiring %d stale approval(s)", len(stale))
    for dl_id, dl in stale:
        self.downloads.pop(dl_id, None)
        await self._cleanup_download_artifacts(dl)
        if dl.approval_message_id:
            try:
                await application.bot.edit_message_caption(
                    chat_id=dl.chat_id,
                    message_id=dl.approval_message_id,
                    caption=self.t(dl.chat_id, "approval_expired"),
                )
            except Exception:
                try:
                    await application.bot.edit_message_text(
                        chat_id=dl.chat_id,
                        message_id=dl.approval_message_id,
                        text=self.t(dl.chat_id, "approval_expired"),
                    )
                except Exception:
                    logger.debug("Could not edit expired approval message %s", dl.approval_message_id)
