"""Expire stale awaiting-approval downloads and delete leftover files."""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

_SWEEP_INTERVAL_SECS = 900


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
                    caption="⏹ Approval expired — file discarded.",
                )
            except Exception:
                try:
                    await application.bot.edit_message_text(
                        chat_id=dl.chat_id,
                        message_id=dl.approval_message_id,
                        text="⏹ Approval expired — file discarded.",
                    )
                except Exception:
                    logger.debug("Could not edit expired approval message %s", dl.approval_message_id)
