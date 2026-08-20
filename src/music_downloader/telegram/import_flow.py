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
from music_downloader.i18n.catalog import gettext as _
from music_downloader.i18n.catalog import set_locale
from music_downloader.playlist_import.job import JobStatus, TrackStatus
from music_downloader.soulseek.errors import SlskdUnavailableError
from music_downloader.soulseek.query import clean_search_title
from music_downloader.soulseek.result import SearchResult
from music_downloader.telegram.download_flow import TELEGRAM_FILE_LIMIT
from music_downloader.telegram.keyboards import (
    build_import_confirm_keyboard,
    build_import_failure_keyboard,
    build_import_skip_keyboard,
    build_import_summary_keyboard,
    build_import_track_keyboard,
)
from music_downloader.telegram.messages import escape_md, md_code_safe, progress_bar, safe_edit, safe_query_edit
from music_downloader.telegram.session import PendingDownload, PendingSearch

logger = logging.getLogger(__name__)


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


async def cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel — cancel active import or search."""
    if not await self._check_auth(update):
        return

    chat_id = update.effective_chat.id

    job_id = self._active_import.pop(chat_id, None)
    if job_id:
        await asyncio.to_thread(self.import_repo.update_job_status, job_id, JobStatus.cancelled)
        await self._cancel_chat_operations(chat_id)
        await update.message.reply_text(_("❌ Import cancelled."))
        return

    active = await asyncio.to_thread(self.import_repo.get_active_job, chat_id)
    if active:
        await asyncio.to_thread(self.import_repo.update_job_status, active.id, JobStatus.cancelled)
        await self._cancel_chat_operations(chat_id)
        await update.message.reply_text(_("❌ Import cancelled."))
        return

    had_work = await self._cancel_chat_operations(chat_id)
    if had_work:
        await update.message.reply_text(_("❌ Cancelled."))
    else:
        await update.message.reply_text(_("Nothing to cancel."))


async def handle_import_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, data: str):
    """Route import-related callbacks (ic/ix/ia/ir/is prefixes)."""
    query = update.callback_query
    prefix, _sep, payload = data.partition(":")
    parts = payload.split(":")

    try:
        job_id = int(parts[0])
    except (IndexError, ValueError):
        return

    job = await asyncio.to_thread(self.import_repo.get_job_for_chat, job_id, chat_id)
    if not job:
        await safe_query_edit(query, _("⏹ Import not found."))
        return

    if prefix == "ic":
        await safe_query_edit(query, _("✅ Import started! Processing tracks one by one..."))
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
        await safe_query_edit(query, _("❌ Import cancelled."))

    elif prefix == "ia":
        track_id = int(parts[1])
        dl_id = parts[2]
        await self._handle_import_approve(update, context, chat_id, job_id, track_id, dl_id)

    elif prefix == "ir":
        track_id = int(parts[1])
        stale = [k for k, v in self.downloads.items() if v.chat_id == chat_id]
        for stale_id in stale:
            await self._cleanup_download_artifacts(self.downloads.pop(stale_id))
        await asyncio.to_thread(
            self.import_repo.complete_track, job_id, track_id, TrackStatus.failed, "Rejected by user"
        )
        await safe_query_edit(query, _("🗑 Track discarded."))
        generation = self._chat_generation.get(chat_id, 0)
        await self._process_next_import_track(context, chat_id, job_id, generation)

    elif prefix == "is":
        track_id = int(parts[1])
        await asyncio.to_thread(self.import_repo.complete_track, job_id, track_id, TrackStatus.skipped)
        await safe_query_edit(query, _("⏭ Track skipped."))
        generation = self._chat_generation.get(chat_id, 0)
        await self._process_next_import_track(context, chat_id, job_id, generation)

    elif prefix == "iy":
        track_id = int(parts[1])
        dl_id = parts[2]
        await self._handle_import_retry(update, context, chat_id, job_id, track_id, dl_id)

    elif prefix == "if":
        await self._handle_import_retry_failed(update, context, chat_id, job_id)


async def handle_import_retry(self, update, context, chat_id: int, job_id: int, track_id: int, dl_id: str):
    """Retry a failed import download inside the import flow (keeps job tracking)."""
    query = update.callback_query
    pending_dl = self.downloads.get(dl_id)

    if not pending_dl:
        await safe_query_edit(query, _("⏹ Download expired. Use Skip or Mark failed to continue the import."))
        return

    result = pending_dl.result
    track = pending_dl.track

    await safe_query_edit(
        query,
        _("🔄 Retrying: `{file}`...").format(file=md_code_safe(result.basename)),
        parse_mode=ParseMode.MARKDOWN,
    )

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=_("⬇️ Re-downloading from `{user}`...").format(user=md_code_safe(result.username)),
        parse_mode=ParseMode.MARKDOWN,
    )

    await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.searching)
    generation = self._chat_generation.get(chat_id, 0)
    task = context.application.create_task(
        self._do_import_download(context, chat_id, track, result, status_msg, generation, job_id, track_id, dl_id),
        update=update,
    )
    self._track_task(chat_id, task)


async def handle_import_approve(self, update, context, chat_id: int, job_id: int, track_id: int, dl_id: str):
    """Approve a download within an import flow."""
    query = update.callback_query

    if not self._can_save_library(query.from_user.id):
        await self._edit_approval_message(query, _("🚫 You are not allowed to save to the library."))
        return

    pending_dl = self.downloads.pop(dl_id, None)

    if not pending_dl:
        await self._edit_approval_message(query, _("⏹ Download expired"))
        return

    if not pending_dl.source_path:
        await self._edit_approval_message(query, _("❌ Source file not ready. Download may still be in progress."))
        self.downloads[dl_id] = pending_dl
        return

    track = pending_dl.track
    result = pending_dl.result

    target_path = self.processor.process_file(pending_dl.source_path, track.artist, track.title)
    if target_path:
        await self._remove_download_file(pending_dl.source_path)
        await self._embed_spotify_artwork(target_path, track)
        target_name = os.path.basename(target_path)
        await self._edit_approval_message(query, _("✅ Saved: `{name}`").format(name=target_name))
        await self._add_history(track, result, "success", chat_id=chat_id)
        await asyncio.to_thread(self.import_repo.complete_track, job_id, track_id, TrackStatus.completed)
    else:
        await self._edit_approval_message(query, _("❌ Failed to save file."))
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
        await _send_import_summary(self, context, chat_id, job_id)
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
        text=_("📋 *Import [{position}/{total}]*\n🔍 Searching: *{artist} - {title}*\nAlbum: {album} ({year})").format(
            position=position,
            total=total,
            artist=escape_md(track_info.artist),
            title=escape_md(track_info.title),
            album=escape_md(track_info.album),
            year=escape_md(track_info.year),
        ),
        parse_mode=ParseMode.MARKDOWN,
    )

    await self._do_import_slskd_search(context, chat_id, track_info, searching_msg, generation, job_id, next_track.id)


async def _send_import_summary(self, context, chat_id: int, job_id: int):
    """Send the end-of-import summary card, listing failures with a retry button."""
    completed, failed, skipped, total = await asyncio.to_thread(self.import_repo.get_job_progress, job_id)
    await asyncio.to_thread(self.import_repo.update_job_status, job_id, JobStatus.completed)
    self._active_import.pop(chat_id, None)

    lines = [
        _("🏁 *Import complete!*") + "\n",
        _("✅ Saved: {saved}\n❌ Failed: {failed}\n⏭ Skipped: {skipped}\n📊 Total: {total}").format(
            saved=completed, failed=failed, skipped=skipped, total=total
        ),
    ]

    reply_markup = None
    if failed:
        failed_tracks = await asyncio.to_thread(self.import_repo.get_failed_tracks, job_id)
        if failed_tracks:
            lines.append("\n" + _("*Failed tracks:*"))
            for t in failed_tracks[:5]:
                lines.append(f"• {escape_md(t.artist)} - {escape_md(t.title)}")
            if len(failed_tracks) > 5:
                lines.append(_("…and {n} more").format(n=len(failed_tracks) - 5))
            reply_markup = build_import_summary_keyboard(job_id, len(failed_tracks))

    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
    )


async def handle_import_retry_failed(self, update, context, chat_id: int, job_id: int):
    """Reset failed tracks to pending and continue the job (summary retry button)."""
    query = update.callback_query

    reset = await asyncio.to_thread(self.import_repo.reset_failed_tracks, job_id)
    if not reset:
        await safe_query_edit(query, _("Nothing to retry — no failed tracks left."))
        return

    await safe_query_edit(
        query,
        _("🔄 Retrying {n} failed track(s)...").format(n=reset),
    )
    self._active_import[chat_id] = job_id
    generation = self._chat_generation.get(chat_id, 0)
    task = context.application.create_task(
        self._process_next_import_track(context, chat_id, job_id, generation),
        update=update,
    )
    self._track_task(chat_id, task)


async def do_import_slskd_search(
    self, context, chat_id: int, track: TrackInfo, searching_msg, generation: int, job_id: int, track_id: int
):
    """Search slskd for an import track using the same four-tier fallbacks as manual search."""
    try:
        search_query = f"{track.artist} {clean_search_title(track.title)}"
        ranked, is_fallback, stale = await self._search_with_fallbacks(track, chat_id, generation)
        if stale:
            return

        if not ranked:
            await safe_edit(
                searching_msg,
                _("📋 *Import track:* {artist} - {title}\n\nNo results found on Soulseek.").format(
                    artist=escape_md(track.artist), title=escape_md(track.title)
                ),
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
            _("📋 *Import track:* {artist} - {title}\n⬇️ Downloading: `{file}`\nFrom: `{user}` | {quality}").format(
                artist=escape_md(track.artist),
                title=escape_md(track.title),
                file=md_code_safe(best.basename),
                user=md_code_safe(best.username),
                quality=best.quality_display,
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

        task = context.application.create_task(
            self._do_import_download(context, chat_id, track, best, searching_msg, generation, job_id, track_id, dl_id),
            update=None,
        )
        self._track_task(chat_id, task)

    except SlskdUnavailableError:
        logger.exception("slskd unreachable during import search for: %s - %s", track.artist, track.title)
        await safe_edit(
            searching_msg,
            _("Cannot reach slskd. Check `SLSKD_HOST` and the API key."),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_import_skip_keyboard(job_id, track_id),
        )
        await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.awaiting_approval)
    except Exception:
        logger.exception(f"Import search failed for: {track.artist} - {track.title}")
        await safe_edit(
            searching_msg,
            _("❌ Search failed for {artist} - {title}").format(artist=track.artist, title=track.title),
        )
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
        success = await asyncio.to_thread(self.slskd.enqueue_download, result)
        if not success:
            await safe_edit(
                status_msg,
                _("❌ Failed to enqueue from `{user}`").format(user=md_code_safe(result.username)),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_import_track_keyboard(job_id, track_id, dl_id),
            )
            await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.awaiting_approval)
            return

        last_edited_pct = -100.0

        async def _on_progress(progress) -> None:
            nonlocal last_edited_pct
            pct = progress.percent_complete
            if dl_id in self.downloads:
                self.downloads[dl_id].progress_percent = pct
                self.downloads[dl_id].transfer_id = progress.transfer_id or self.downloads[dl_id].transfer_id
            if pct - last_edited_pct < 10:
                return
            last_edited_pct = pct
            await safe_edit(
                status_msg,
                _("📋 *Import track:* {artist} - {title}\n⬇️ Downloading {pct}%\n{bar}\n`{file}`").format(
                    artist=escape_md(track.artist),
                    title=escape_md(track.title),
                    pct=f"{pct:.0f}",
                    bar=progress_bar(pct),
                    file=md_code_safe(result.basename),
                ),
                parse_mode=ParseMode.MARKDOWN,
            )

        status = await self.slskd.wait_for_download(
            username=result.username,
            filename=result.filename,
            timeout_secs=self.config.download_timeout_secs,
            progress_callback=_on_progress,
        )
        transfer_id = status.transfer_id if status else None
        if dl_id in self.downloads:
            self.downloads[dl_id].transfer_id = transfer_id or self.downloads[dl_id].transfer_id

        if status is None or status.is_failed:
            state = status.state if status else _("Timeout")
            await safe_edit(
                status_msg,
                _("❌ Download failed: {state}\n`{file}`").format(state=state, file=md_code_safe(result.basename)),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=build_import_failure_keyboard(job_id, track_id, dl_id),
            )
            await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.awaiting_approval)
            return

        source_path = self.processor.find_downloaded_file(result.username, result.filename)
        if not source_path:
            await safe_edit(
                status_msg,
                _("❌ Downloaded file not found on disk."),
                reply_markup=build_import_track_keyboard(job_id, track_id, dl_id),
            )
            await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.awaiting_approval)
            return

        if dl_id in self.downloads:
            self.downloads[dl_id].source_path = source_path

        await asyncio.to_thread(self.import_repo.update_track_status, track_id, TrackStatus.awaiting_approval)

        file_size = os.path.getsize(source_path) if os.path.isfile(source_path) else 0
        quality_line = f"{result.quality_display} | {result.duration_display}"
        caption = _("📋 Import: {artist} - {title}\n{quality}").format(
            artist=track.artist, title=track.title, quality=quality_line
        )

        if file_size > TELEGRAM_FILE_LIMIT:
            await safe_edit(
                status_msg,
                _(
                    "✅ Downloaded: `{file}` ({size:.0f}MB)\n{quality}\n\nFile too large to preview. Save to library?"
                ).format(
                    file=md_code_safe(result.basename),
                    size=file_size / (1024 * 1024),
                    quality=quality_line,
                ),
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
        pending_dl = self.downloads.pop(dl_id, None)
        if pending_dl:
            await self._cleanup_download_artifacts(pending_dl)
        else:
            await asyncio.to_thread(self.slskd.cancel_transfer, result.username, result.filename, None)
        raise
    except Exception:
        logger.exception(f"Import download failed for {result.basename}")
        await safe_edit(
            status_msg,
            _("❌ Error downloading `{file}`").format(file=md_code_safe(result.basename)),
            parse_mode=ParseMode.MARKDOWN,
        )
        await asyncio.to_thread(self.import_repo.complete_track, job_id, track_id, TrackStatus.failed, "Download error")
        await self._process_next_import_track(context, chat_id, job_id, generation)


class _ResumeContext:
    """Minimal context so import resume can use Application.bot / create_task."""

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
    locale = self.locale_store.get(chat_id)
    if locale:
        set_locale(locale)

    if job is None:
        job = await asyncio.to_thread(self.import_repo.get_active_job, chat_id)
    if not job:
        if notify:
            await context.bot.send_message(chat_id=chat_id, text=_("Nothing to resume."))
        return

    if self._active_import.get(chat_id) == job.id:
        if notify:
            await context.bot.send_message(
                chat_id=chat_id,
                text=_("Import of *{name}* is already running.").format(name=escape_md(job.name)),
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
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    _("Resuming import of *{name}* ({remaining} remaining, {done} done).").format(
                        name=escape_md(job.name),
                        remaining=remaining,
                        done=job.completed_tracks,
                    )
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            logger.warning("Could not notify chat %s about import resume", chat_id)

    app = getattr(context, "application", context)
    task = app.create_task(
        self._process_next_import_track(context, chat_id, job.id, generation),
    )
    self._track_task(chat_id, task)
