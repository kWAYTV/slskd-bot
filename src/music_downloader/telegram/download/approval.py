"""Save-to-library approval: approve, reject, and dismissing stale downloads."""

from __future__ import annotations

import contextlib
import logging
import os

from music_downloader.i18n.catalog import gettext as _
from music_downloader.telegram.ui.markdown import escape_md

logger = logging.getLogger(__name__)


async def handle_approval(self, update, context, chat_id: int, data: str):
    """Handle approve/reject of a downloaded file."""
    query = update.callback_query
    action, dl_id = data.split(":", 1)

    pending_dl = self.downloads.pop(dl_id, None)
    if not pending_dl:
        await self._edit_approval_message(query, _("⏹ Cancelled"))
        return

    if pending_dl.chat_id != chat_id:
        self.downloads[dl_id] = pending_dl
        return

    track = pending_dl.track
    result = pending_dl.result

    if action == "approve":
        if not self._can_save_library(query.from_user.id):
            self.downloads[dl_id] = pending_dl
            await self._edit_approval_message(query, _("🚫 You are not allowed to save to the library."))
            return
        if pending_dl.source_path:
            target_path = self.processor.process_file(pending_dl.source_path, track.artist, track.title)
            if target_path:
                await self._remove_download_file(pending_dl.source_path)
                await self._embed_spotify_artwork(target_path, track)
                target_name = os.path.basename(target_path)
                await self._edit_approval_message(query, _("✅ Saved: `{name}`").format(name=target_name))
                await self._add_history(track, result, "success", chat_id=chat_id)
                logger.info(f"Approved and saved: {target_name}")
                await self._dismiss_other_downloads(context, chat_id)
            else:
                await self._edit_approval_message(query, _("❌ Failed to save file. Check logs."))
                await self._add_history(track, result, "process_failed", chat_id=chat_id)
        else:
            await self._edit_approval_message(query, _("❌ Source file not found."))
            await self._add_history(track, result, "file_not_found", chat_id=chat_id)

    elif action == "reject":
        await self._cleanup_download_artifacts(pending_dl)
        await self._edit_approval_message(
            query,
            _("🗑 Discarded: {artist} - {title}").format(artist=escape_md(track.artist), title=escape_md(track.title)),
        )
        await self._add_history(track, result, "rejected", chat_id=chat_id)
        logger.info(f"Rejected: {track.artist} - {track.title} ({result.basename})")


async def dismiss_other_downloads(self, context, chat_id: int):
    """Cancel all remaining pending downloads for a chat after one is approved."""
    pending = self.pending.pop(chat_id, None)
    if pending and pending.message_id:
        with contextlib.suppress(Exception):
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=pending.message_id,
            )

    stale = [(k, v) for k, v in self.downloads.items() if v.chat_id == chat_id]
    for dl_id, dl in stale:
        del self.downloads[dl_id]
        await self._cleanup_download_artifacts(dl)
        if dl.approval_message_id:
            try:
                await context.bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=dl.approval_message_id,
                    caption=_("⏹ Cancelled"),
                )
            except Exception:
                with contextlib.suppress(Exception):
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=dl.approval_message_id,
                        text=_("⏹ Cancelled"),
                    )

    for task in self._active_tasks.pop(chat_id, set()):
        task.cancel()
