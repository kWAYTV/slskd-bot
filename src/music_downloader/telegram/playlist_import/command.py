"""/import — resolve a Spotify playlist/album and confirm the import job."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from music_downloader.catalog.playlist import PlaylistResolver
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
                (
                    f"You have an unfinished import: *{escape_md(active.name)}* ({active.completed_tracks}/{active.total_tracks}).\n"
                    "Send `/import resume` to continue, or /cancel to stop it."
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        await update.message.reply_text(
            ("Usage: `/import <spotify_playlist_or_album_url>` or `/import resume`"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    url = extra

    if not PlaylistResolver.is_spotify_url(url):
        await update.message.reply_text(
            ("Please provide a valid Spotify playlist or album URL."),
        )
        return

    await start_import_from_url(self, update, context, chat_id, url)


async def start_import_from_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, url: str):
    """Resolve a playlist/album URL, create the job, and show the confirm keyboard."""
    active = await asyncio.to_thread(self.import_repo.get_active_job, chat_id)
    if active:
        await update.message.reply_text(
            (
                f"You already have an active import: *{escape_md(active.name)}* ({active.completed_tracks}/{active.total_tracks})\n"
                "Send `/import resume` to continue, or /cancel to stop it first."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    status_msg = await update.message.reply_text("🔍 Resolving playlist...")

    playlist_info = await asyncio.to_thread(self.playlist_resolver.resolve, url)
    if not playlist_info:
        await safe_edit(status_msg, ("Failed to resolve playlist. Check the URL and try again."))
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

    type_label = ("album") if playlist_info.is_album else ("playlist")
    await safe_edit(
        status_msg,
        (
            f"📋 Found {type_label}: *{escape_md(playlist_info.name)}*\nBy: {escape_md(playlist_info.owner)}\nTracks: {playlist_info.total_tracks}\n\nImport all tracks one by one?"
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_import_confirm_keyboard(job_id),
    )
