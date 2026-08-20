"""/import — resolve a Spotify playlist/album and confirm the import job."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from music_downloader.catalog.playlist import PlaylistResolver
from music_downloader.i18n.catalog import gettext as _
from music_downloader.telegram.playlist_import.resume import resume_import_job
from music_downloader.telegram.ui.editing import safe_edit
from music_downloader.telegram.ui.keyboards import build_import_confirm_keyboard
from music_downloader.telegram.ui.markdown import escape_md


async def cmd_import(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /import <spotify_url> — import playlist or album."""
    if not await self._check_library_auth(update):
        return

    chat_id = update.effective_chat.id
    args = update.message.text.split(maxsplit=1)
    extra = args[1].strip() if len(args) >= 2 else ""

    if extra.lower() == "resume":
        await resume_import_job(self, context, chat_id, notify=True)
        return

    if not extra:
        active = await asyncio.to_thread(self.import_repo.get_active_job, chat_id)
        if active:
            await update.message.reply_text(
                _(
                    "You have an unfinished import: *{name}* ({done}/{total}).\n"
                    "Send `/import resume` to continue, or /cancel to stop it."
                ).format(
                    name=escape_md(active.name),
                    done=active.completed_tracks,
                    total=active.total_tracks,
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        await update.message.reply_text(
            _("Usage: `/import <spotify_playlist_or_album_url>` or `/import resume`"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    url = extra

    if not PlaylistResolver.is_spotify_url(url):
        await update.message.reply_text(
            _("Please provide a valid Spotify playlist or album URL."),
        )
        return

    active = await asyncio.to_thread(self.import_repo.get_active_job, chat_id)
    if active:
        await update.message.reply_text(
            _(
                "You already have an active import: *{name}* ({done}/{total})\n"
                "Send `/import resume` to continue, or /cancel to stop it first."
            ).format(
                name=escape_md(active.name),
                done=active.completed_tracks,
                total=active.total_tracks,
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    status_msg = await update.message.reply_text(_("🔍 Resolving playlist..."))

    playlist_info = await asyncio.to_thread(self.playlist_resolver.resolve, url)
    if not playlist_info:
        await safe_edit(status_msg, _("Failed to resolve playlist. Check the URL and try again."))
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

    type_label = _("album") if playlist_info.is_album else _("playlist")
    await safe_edit(
        status_msg,
        _("📋 Found {kind}: *{name}*\nBy: {owner}\nTracks: {total}\n\nImport all tracks one by one?").format(
            kind=type_label,
            name=escape_md(playlist_info.name),
            owner=escape_md(playlist_info.owner),
            total=playlist_info.total_tracks,
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_import_confirm_keyboard(job_id),
    )
