"""/import — resolve a Spotify playlist/album and confirm the import job."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from slskd_importer.catalog.playlist import PlaylistResolver
from slskd_importer.telegram.playlist_import.keyboards import build_import_confirm_keyboard
from slskd_importer.telegram.playlist_import.resume import resume_import_job
from slskd_importer.telegram.ui.editing import safe_edit
from slskd_importer.telegram.ui.markdown import escape_md

logger = logging.getLogger(__name__)


async def cmd_import(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /import <spotify_url> — import playlist or album."""
    if not await self._check_library_auth(update):
        return

    chat_id = update.effective_chat.id
    args = update.message.text.split(maxsplit=1)
    extra = args[1].strip() if len(args) >= 2 else ""

    if extra.lower() == "resume" or not extra:
        active = await asyncio.to_thread(self.import_repo.get_active_job, chat_id)
        if active or extra.lower() == "resume":
            await resume_import_job(self, context, chat_id, notify=True)
            return
        await update.message.reply_text(
            self.t(chat_id, "import_usage"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    url = extra

    if not PlaylistResolver.is_spotify_url(url):
        await update.message.reply_text(self.t(chat_id, "import_invalid_url"))
        return

    task = context.application.create_task(
        start_import_from_url(self, update, context, chat_id, url),
        update=update,
    )
    self._track_task(chat_id, task)


async def start_import_from_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, url: str):
    """Resolve a playlist/album URL, create the job, and show the confirm keyboard."""
    active = await asyncio.to_thread(self.import_repo.get_active_job, chat_id)
    if active:
        await update.message.reply_text(
            self.t(
                chat_id,
                "import_active",
                name=escape_md(active.name),
                done=active.completed_tracks,
                total=active.total_tracks,
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    status_msg = await update.message.reply_text(self.t(chat_id, "import_resolving"))

    playlist_info = await asyncio.to_thread(self.playlist_resolver.resolve, url)
    if not playlist_info:
        await safe_edit(status_msg, self.t(chat_id, "import_failed_resolve"))
        return

    job_id = await asyncio.to_thread(
        self.import_repo.create_job,
        chat_id=chat_id,
        spotify_url=url,
        name=playlist_info.name,
        total_tracks=playlist_info.total_tracks,
    )

    track_dicts = [
        {
            "position": i + 1,
            "artist": t.artist,
            "title": t.title,
            "album": t.album,
            "duration_ms": t.duration_ms,
            "spotify_url": t.spotify_url,
            "year": t.year,
        }
        for i, t in enumerate(playlist_info.tracks)
    ]
    await asyncio.to_thread(self.import_repo.add_tracks, job_id, track_dicts)
    logger.info(
        "chat=%s created import job %s (%s, %d tracks): %s",
        chat_id,
        job_id,
        "album" if playlist_info.is_album else "playlist",
        playlist_info.total_tracks,
        playlist_info.name,
    )

    type_label = self.t(chat_id, "kind_album" if playlist_info.is_album else "kind_playlist")
    await safe_edit(
        status_msg,
        self.t(
            chat_id,
            "import_found",
            kind=type_label,
            name=escape_md(playlist_info.name),
            owner=escape_md(playlist_info.owner),
            total=playlist_info.total_tracks,
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_import_confirm_keyboard(job_id, locale=self.locale(chat_id)),
    )
