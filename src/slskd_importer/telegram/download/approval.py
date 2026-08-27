"""Save-to-library approval: approve, reject, and dismissing sibling downloads."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from slskd_importer.telegram.ui.markdown import escape_md

logger = logging.getLogger(__name__)


async def handle_approval(self, update, context, chat_id: int, data: str):
    """Handle approve/reject of a downloaded file."""
    query = update.callback_query
    action, dl_id = data.split(":", 1)

    pending_dl = self.downloads.pop(dl_id, None)
    if not pending_dl:
        await self._edit_approval_message(query, self.t(chat_id, "approval_cancelled"))
        return

    if pending_dl.chat_id != chat_id:
        self.downloads[dl_id] = pending_dl
        return

    if action == "approve":
        await _approve_download(self, query, context, chat_id, dl_id, pending_dl)
        return
    if action == "reject":
        await _reject_download(self, query, chat_id, pending_dl)


async def save_to_library(self, pending_dl, chat_id: int) -> str | None:
    """Shared save sequence: rename into the library, embed artwork, record history.

    Returns the saved basename, or None when file processing failed.
    """
    track = pending_dl.track
    result = pending_dl.result
    target_path = await asyncio.to_thread(
        self.processor.process_file,
        pending_dl.source_path,
        track.artist,
        track.title,
        album=track.album,
        year=track.year,
    )
    if not target_path:
        return None
    await self._remove_download_file(pending_dl.source_path)
    await self._embed_spotify_artwork(target_path, track)
    await self._add_history(track, result, "success", chat_id=chat_id)
    return os.path.basename(target_path)


async def _approve_download(self, query, context, chat_id: int, dl_id: str, pending_dl):
    """Save an approved download to the library."""
    track = pending_dl.track
    result = pending_dl.result

    if not self._can_save_library(query.from_user.id):
        self.downloads[dl_id] = pending_dl
        await self._edit_approval_message(query, self.t(chat_id, "approval_denied"))
        return

    if not pending_dl.source_path:
        await self._edit_approval_message(query, self.t(chat_id, "approval_no_source"))
        await self._add_history(track, result, "file_not_found", chat_id=chat_id)
        return

    target_name = await save_to_library(self, pending_dl, chat_id)
    if not target_name:
        await self._edit_approval_message(query, self.t(chat_id, "approval_save_failed"))
        await self._add_history(track, result, "process_failed", chat_id=chat_id)
        return

    await self._edit_approval_message(query, self.t(chat_id, "saved", name=target_name))
    logger.info("chat=%s approved and saved: %s", chat_id, target_name)
    await self._dismiss_other_downloads(context, chat_id, search_id=pending_dl.search_id)


async def _reject_download(self, query, chat_id: int, pending_dl):
    """Discard a rejected download and its local artifacts."""
    track = pending_dl.track
    result = pending_dl.result

    await self._cleanup_download_artifacts(pending_dl)
    await self._edit_approval_message(
        query,
        self.t(chat_id, "discarded", artist=escape_md(track.artist), title=escape_md(track.title)),
    )
    await self._add_history(track, result, "rejected", chat_id=chat_id)
    logger.info("chat=%s rejected: %s - %s (%s)", chat_id, track.artist, track.title, result.basename)


async def dismiss_other_downloads(self, context, chat_id: int, search_id: str | None = None):
    """Cancel sibling downloads from the same search after one is approved.

    Other chats' work and unrelated searches in this chat are left alone.
    """
    if search_id:
        pending = self._session.drop_search(search_id)
        if pending and pending.message_id:
            with contextlib.suppress(Exception):
                await context.bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=pending.message_id,
                )

    stale = [(k, v) for k, v in self.downloads.items() if v.chat_id == chat_id and v.search_id == search_id]
    for dl_id, dl in stale:
        del self.downloads[dl_id]
        if dl.task is not None:
            dl.task.cancel()
        await self._cleanup_download_artifacts(dl)
        if dl.approval_message_id:
            await _mark_message_cancelled(self, context, chat_id, dl.approval_message_id)
        elif dl.status_message_id:
            await _mark_message_cancelled(self, context, chat_id, dl.status_message_id)


async def _mark_message_cancelled(self, context, chat_id: int, message_id: int):
    """Replace a stale approval message with a cancelled notice (caption or text)."""
    try:
        await context.bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=self.t(chat_id, "approval_cancelled"),
        )
    except Exception:
        with contextlib.suppress(Exception):
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=self.t(chat_id, "approval_cancelled"),
            )
