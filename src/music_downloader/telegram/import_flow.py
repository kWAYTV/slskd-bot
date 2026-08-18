"""Playlist/album import conversation."""

from __future__ import annotations

import asyncio
import logging
import os

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from music_downloader.catalog.playlist import PlaylistResolver
from music_downloader.catalog.track import TrackInfo
from music_downloader.playlist_import.job import JobStatus, TrackStatus
from music_downloader.soulseek.query import clean_search_title
from music_downloader.soulseek.result import SearchResult
from music_downloader.telegram.download_flow import TELEGRAM_FILE_LIMIT
from music_downloader.telegram.keyboards import (
    build_import_confirm_keyboard,
    build_import_skip_keyboard,
    build_import_track_keyboard,
    build_retry_keyboard,
)
from music_downloader.telegram.messages import escape_md, safe_edit, safe_query_edit
from music_downloader.telegram.session import PendingDownload, PendingSearch

logger = logging.getLogger(__name__)


async def cmd_import(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /import <spotify_url> — import playlist or album."""
    if not await self._check_auth(update):
        return

    chat_id = update.effective_chat.id
    args = update.message.text.split(maxsplit=1)

    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/import <spotify_playlist_or_album_url>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    url = args[1].strip()

    if not PlaylistResolver.is_spotify_url(url):
        await update.message.reply_text(
            "Please provide a valid Spotify playlist or album URL.",
        )
        return

    active = await asyncio.to_thread(self.import_repo.get_active_job, chat_id)
    if active:
        await update.message.reply_text(
            f"You already have an active import: *{escape_md(active.name)}* ({active.completed_tracks}/{active.total_tracks})\n"
            f"Use /cancel to stop it first.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    status_msg = await update.message.reply_text("\U0001f50d Resolving playlist...")

    playlist_info = await asyncio.to_thread(self.playlist_resolver.resolve, url)
    if not playlist_info:
        await safe_edit(status_msg, "Failed to resolve playlist. Check the URL and try again.")
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

    type_label = "album" if playlist_info.is_album else "playlist"
    await safe_edit(
        status_msg,
        f"\U0001f4cb Found {type_label}: *{escape_md(playlist_info.name)}*\n"
        f"By: {escape_md(playlist_info.owner)}\n"
        f"Tracks: {playlist_info.total_tracks}\n\n"
        f"Import all tracks one by one?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_import_confirm_keyboard(job_id),
    )


async def cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel — cancel active import or search."""
    if not await self._check_auth(update):
        return

    chat_id = update.effective_chat.id

    job_id = self._active_import.pop(chat_id, None)
    if job_id:
        await asyncio.to_thread(self.import_repo.update_job_status, job_id, JobStatus.cancelled)
        self._cancel_chat_operations(chat_id)
        await update.message.reply_text("❌ Import cancelled.")
        return

    had_work = self._cancel_chat_operations(chat_id)
    if had_work:
        await update.message.reply_text("❌ Cancelled.")
    else:
        await update.message.reply_text("Nothing to cancel.")


async def handle_import_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, data: str):
    """Route import-related callbacks (ic/ix/ia/ir/is prefixes)."""
    query = update.callback_query
    prefix, _, payload = data.partition(":")
    parts = payload.split(":")

    try:
        job_id = int(parts[0])
    except (IndexError, ValueError):
        return

    job = await asyncio.to_thread(self.import_repo.get_job_for_chat, job_id, chat_id)
    if not job:
        await safe_query_edit(query, "⏹ Import not found.")
        return

    if prefix == "ic":
        await safe_query_edit(query, "✅ Import started! Processing tracks one by one...")
        await asyncio.to_thread(self.import_repo.update_job_status, job_id, JobStatus.active)
        self._active_import[chat_id] = job_id
        generation = self._chat_generation.get(chat_id, 0)
        task = context.application.create_task(
            self._process_next_import_track(context, chat_id, job_id, generation),
            update=update,
        )
        self._track_task(chat_id, task)

    elif prefix == "ix":
        await asyncio.to_thread(self.import_repo.update_job_status, job_id, JobStatus.cancelled)
        self._active_import.pop(chat_id, None)
        await safe_query_edit(query, "❌ Import cancelled.")

    elif prefix == "ia":
        track_id = int(parts[1])
        dl_id = parts[2]
        await self._handle_import_approve(update, context, chat_id, job_id, track_id, dl_id)

    elif prefix == "ir":
        track_id = int(parts[1])
        await asyncio.to_thread(
            self.import_repo.complete_track, job_id, track_id, TrackStatus.failed, "Rejected by user"
        )
        await safe_query_edit(query, "\U0001f6ab Track rejected.")
        generation = self._chat_generation.get(chat_id, 0)
        await self._process_next_import_track(context, chat_id, job_id, generation)

    elif prefix == "is":
        track_id = int(parts[1])
        await asyncio.to_thread(self.import_repo.complete_track, job_id, track_id, TrackStatus.skipped)
        await safe_query_edit(query, "⏭ Track skipped.")
        generation = self._chat_generation.get(chat_id, 0)
        await self._process_next_import_track(context, chat_id, job_id, generation)


async def handle_import_approve(self, update, context, chat_id: int, job_id: int, track_id: int, dl_id: str):
    """Approve a download within an import flow."""
    query = update.callback_query
    pending_dl = self.downloads.pop(dl_id, None)

    if not pending_dl:
        await self._edit_approval_message(query, "⏹ Download expired")
        return

    if not pending_dl.source_path:
        await self._edit_approval_message(query, "❌ Source file not ready. Download may still be in progress.")
        self.downloads[dl_id] = pending_dl
        return

    track = pending_dl.track
    result = pending_dl.result

    target_path = self.processor.process_file(pending_dl.source_path, track.artist, track.title)
    if target_path:
        self.processor.cleanup_download(pending_dl.source_path)
        await self._embed_spotify_artwork(target_path, track)
        target_name = os.path.basename(target_path)
        await self._edit_approval_message(query, f"✅ Saved: `{target_name}`")
        await self._add_history(track, result, "success")
        await asyncio.to_thread(self.import_repo.complete_track, job_id, track_id, TrackStatus.completed)
    else:
        await self._edit_approval_message(query, "❌ Failed to save file.")
        await asyncio.to_thread(
            self.import_repo.complete_track, job_id, track_id, TrackStatus.failed, "File processing failed"
        )

    generation = self._chat_generation.get(chat_id, 0)
    await self._process_next_import_track(context, chat_id, job_id, generation)


async def process_next_import_track(self, context, chat_id: int, job_id: int, generation: int):
    """Process the next pending track in an import job."""
    if self._is_stale(chat_id, generation):
        return

    next_track = await asyncio.to_thread(self.import_repo.get_next_pending_track, job_id)

    if not next_track:
        progress = await asyncio.to_thread(self.import_repo.get_job_progress, job_id)
        completed, failed, skipped, total = progress
        await asyncio.to_thread(self.import_repo.update_job_status, job_id, JobStatus.completed)
        self._active_import.pop(chat_id, None)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"\U0001f3c1 *Import complete!*\n\n"
            f"✅ Saved: {completed}\n"
            f"❌ Failed: {failed}\n"
            f"⏭ Skipped: {skipped}\n"
            f"\U0001f4ca Total: {total}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    track_info = TrackInfo(
        artist=next_track.artist,
        title=next_track.title,
        album=next_track.album,
        duration_ms=next_track.duration_ms,
        spotify_url=next_track.spotify_url,
        year=next_track.year,
    )

    progress = await asyncio.to_thread(self.import_repo.get_job_progress, job_id)
    completed, failed, skipped, total = progress
    position = completed + failed + skipped + 1

    await asyncio.to_thread(self.import_repo.update_track_status, next_track.id, TrackStatus.searching)

    searching_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"\U0001f4cb *Import [{position}/{total}]*\n"
        f"\U0001f50d Searching: *{track_info.artist} - {track_info.title}*\n"
        f"Album: {track_info.album} ({track_info.year})",
        parse_mode=ParseMode.MARKDOWN,
    )

    await self._do_import_slskd_search(context, chat_id, track_info, searching_msg, generation, job_id, next_track.id)


async def do_import_slskd_search(
    self, context, chat_id: int, track: TrackInfo, searching_msg, generation: int, job_id: int, track_id: int
):
    """Search slskd for an import track."""
    try:
        clean_title = clean_search_title(track.title)
        search_query = f"{track.artist} {clean_title}"
        raw_responses = await self.slskd.search(search_query, timeout_secs=self.config.search_timeout_secs)
        if self._is_stale(chat_id, generation):
            return

        ranked, is_fallback = self._rank_responses(raw_responses, track)

        if not ranked:
            if self._is_stale(chat_id, generation):
                return
            raw_responses = await self.slskd.search(clean_title, timeout_secs=self.config.search_timeout_secs)
            if self._is_stale(chat_id, generation):
                return
            ranked, is_fallback = self._rank_responses(raw_responses, track)

        if self._is_stale(chat_id, generation):
            return

        if not ranked:
            await safe_edit(
                searching_msg,
                f"\U0001f4cb *Import track:* {track.artist} - {track.title}\n\nNo results found on Soulseek.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_import_skip_keyboard(job_id, track_id),
            )
            await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.awaiting_approval)
            return

        best = ranked[0]

        self._import_pending[chat_id] = PendingSearch(
            query=search_query,
            track=track,
            results=ranked,
            message_id=searching_msg.message_id,
            is_fallback=is_fallback,
        )

        dl_id = self._next_dl_id()
        pending_dl = PendingDownload(
            track=track,
            result=best,
            chat_id=chat_id,
            source_path=None,
            status_message_id=searching_msg.message_id,
        )
        self.downloads[dl_id] = pending_dl

        await safe_edit(
            searching_msg,
            f"\U0001f4cb *Import track:* {track.artist} - {track.title}\n"
            f"⬇️ Downloading: `{best.basename}`\n"
            f"From: `{best.username}` | {best.quality_display}",
            parse_mode=ParseMode.MARKDOWN,
        )

        task = context.application.create_task(
            self._do_import_download(context, chat_id, track, best, searching_msg, generation, job_id, track_id, dl_id),
            update=None,
        )
        self._track_task(chat_id, task)

    except Exception:
        logger.exception(f"Import search failed for: {track.artist} - {track.title}")
        await safe_edit(searching_msg, f"❌ Search failed for {track.artist} - {track.title}")
        await asyncio.to_thread(self.import_repo.complete_track, job_id, track_id, TrackStatus.failed, "Search error")
        await self._process_next_import_track(context, chat_id, job_id, generation)


async def do_import_download(
    self,
    context,
    chat_id: int,
    track: TrackInfo,
    result: SearchResult,
    status_msg,
    generation: int,
    job_id: int,
    track_id: int,
    dl_id: str,
):
    """Download a file within an import flow."""
    try:
        success = self.slskd.enqueue_download(result)
        if not success:
            await safe_edit(
                status_msg,
                f"❌ Failed to enqueue from `{result.username}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_import_track_keyboard(job_id, track_id, dl_id),
            )
            await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.awaiting_approval)
            return

        status = await self.slskd.wait_for_download(
            username=result.username,
            filename=result.filename,
            timeout_secs=self.config.download_timeout_secs,
        )

        if status is None or status.is_failed:
            state = status.state if status else "Timeout"
            await safe_edit(
                status_msg,
                f"❌ Download failed: {state}\n`{result.basename}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_retry_keyboard(dl_id),
            )
            await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.awaiting_approval)
            return

        source_path = self.processor.find_downloaded_file(result.username, result.filename)
        if not source_path:
            await safe_edit(
                status_msg,
                "❌ Downloaded file not found on disk.",
                reply_markup=build_import_track_keyboard(job_id, track_id, dl_id),
            )
            await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.awaiting_approval)
            return

        if dl_id in self.downloads:
            self.downloads[dl_id].source_path = source_path

        await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.awaiting_approval)

        file_size = os.path.getsize(source_path) if os.path.isfile(source_path) else 0
        quality_line = f"{result.quality_display} | {result.duration_display}"
        caption = f"\U0001f4cb Import: {track.artist} - {track.title}\n{quality_line}"

        if file_size > TELEGRAM_FILE_LIMIT:
            await safe_edit(
                status_msg,
                f"✅ Downloaded: `{result.basename}` ({file_size / (1024 * 1024):.0f}MB)\n"
                f"{quality_line}\n\nFile too large to preview. Save to library?",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_import_track_keyboard(job_id, track_id, dl_id),
            )
        else:
            target_name = self.processor.build_filename(track.artist, track.title, result.extension)
            try:
                with open(source_path, "rb") as f:
                    await context.bot.send_audio(
                        chat_id=chat_id,
                        audio=f,
                        filename=target_name,
                        title=track.title,
                        performer=track.artist,
                        duration=track.duration_secs,
                        caption=caption,
                        reply_markup=build_import_track_keyboard(job_id, track_id, dl_id),
                    )
            except BadRequest:
                with open(source_path, "rb") as f:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        filename=target_name,
                        caption=caption,
                        reply_markup=build_import_track_keyboard(job_id, track_id, dl_id),
                    )

    except asyncio.CancelledError:
        self.downloads.pop(dl_id, None)
        raise
    except Exception:
        logger.exception(f"Import download failed for {result.basename}")
        await safe_edit(status_msg, f"❌ Error downloading `{result.basename}`", parse_mode=ParseMode.MARKDOWN)
        await asyncio.to_thread(self.import_repo.complete_track, job_id, track_id, TrackStatus.failed, "Download error")
        await self._process_next_import_track(context, chat_id, job_id, generation)
