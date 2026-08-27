"""The download run: transfer, verify, deliver a preview, ask for approval."""

from __future__ import annotations

import asyncio
import logging
import os

from telegram.constants import ParseMode

from slskd_importer.catalog.track import TrackInfo
from slskd_importer.soulseek.result import SearchResult
from slskd_importer.telegram.core.session import PendingDownload
from slskd_importer.telegram.download.delivery import send_audio_or_document
from slskd_importer.telegram.download.keyboards import (
    build_approve_keyboard,
    build_retry_keyboard,
    build_retry_next_keyboard,
)
from slskd_importer.telegram.download.transfer import (
    abort_transfer,
    fetch_from_peer,
    make_progress_callback,
    remember_approval_message,
)
from slskd_importer.telegram.ui.editing import safe_edit
from slskd_importer.telegram.ui.formatting import format_flac_verdict, format_result_reasons, progress_bar, track_chip
from slskd_importer.telegram.ui.markdown import md_code_safe
from slskd_importer.telegram.ui.reply import collapse_status_message

logger = logging.getLogger(__name__)


async def do_download(
    self,
    context,
    chat_id: int,
    track: TrackInfo,
    result: SearchResult,
    status_msg,
    result_index: int = 0,
    user_id: int | None = None,
    search_id: str | None = None,
):
    """Download a file, send it to Telegram for preview, and ask for approval."""
    dl_id = self._next_dl_id()
    label = f"#{result_index + 1}"
    chip = track_chip(track, label)
    can_save = self._can_save_library(user_id)
    transfer_id = None
    search = self.pending.get(search_id) if search_id else None
    origin_id = search.message_id if search else None

    # Register up front so /status and /cancel see in-flight downloads.
    pending_dl = PendingDownload(
        track=track,
        result=result,
        chat_id=chat_id,
        status_message_id=status_msg.message_id,
        result_index=result_index,
        user_id=user_id,
        search_id=search_id,
        task=asyncio.current_task(),
        origin_message_id=origin_id,
    )
    self.downloads[dl_id] = pending_dl
    logger.info(
        "chat=%s download %s %s: %s - %s from %s (%s)",
        chat_id,
        dl_id,
        label,
        track.artist,
        track.title,
        result.username,
        result.basename,
    )

    render_progress = _progress_renderer(self, status_msg, chip, result, pending_dl)

    try:
        outcome = await fetch_from_peer(self, result, make_progress_callback(pending_dl, render_progress))
        if not outcome.enqueued:
            logger.warning("chat=%s enqueue failed for %s from %s", chat_id, result.basename, result.username)
            await _report_enqueue_failure(self, status_msg, chat_id, result, result_index, dl_id, search_id)
            await self._set_results_pick_state(context, search_id, result_index, "failed")
            return

        status = outcome.status
        transfer_id = status.transfer_id if status else pending_dl.transfer_id
        pending_dl.transfer_id = transfer_id

        if outcome.failed:
            state = status.state if status else ("Timeout")
            logger.warning("chat=%s transfer failed (%s): %s", chat_id, state, result.basename)
            await _report_download_failure(self, status_msg, chat_id, result, result_index, dl_id, state, search_id)
            await self._add_history(track, result, "failed", chat_id=chat_id)
            await self._set_results_pick_state(context, search_id, result_index, "failed")
            return

        source_path = outcome.source_path
        if not source_path:
            logger.error("chat=%s downloaded file missing on disk: %s", chat_id, result.basename)
            self.downloads.pop(dl_id, None)
            await safe_edit(
                status_msg,
                self.t(chat_id, "file_missing"),
            )
            await self._add_history(track, result, "file_not_found", chat_id=chat_id)
            await self._set_results_pick_state(context, search_id, result_index, "failed")
            return

        pending_dl.source_path = source_path
        pending_dl.progress_percent = 100.0

        quality_line = await _build_quality_line(self, chat_id, track, result, source_path)
        await safe_edit(
            status_msg,
            self.t(chat_id, "downloaded_sending", chip=chip, file=md_code_safe(result.basename), quality=quality_line),
            parse_mode=ParseMode.MARKDOWN,
        )

        delivered = await _deliver_preview(
            self,
            context,
            chat_id,
            track,
            result,
            source_path,
            quality_line,
            label,
            chip,
            dl_id,
            result_index,
            can_save,
            search_id,
            origin_id,
        )

        if not can_save:
            # Only record "delivered" when audio actually reached the user.
            status_label = "delivered" if delivered else "failed"
            await _forget_local_copy(self, pending_dl, track, result, chat_id, status=status_label)

    except asyncio.CancelledError:
        logger.info("Download cancelled for %s", result.basename)
        await abort_transfer(self, dl_id, result, transfer_id)
        await safe_edit(status_msg, self.t(chat_id, "cancelled"))
        raise
    except Exception:
        logger.exception(f"Download failed for {result.basename}")
        await safe_edit(
            status_msg,
            self.t(chat_id, "download_error", file=md_code_safe(result.basename)),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_retry_keyboard(self, chat_id, result_index, dl_id, search_id),
        )
        await self._set_results_pick_state(context, search_id, result_index, "failed")


def _progress_renderer(self, status_msg, chip: str, result: SearchResult, pending_dl):
    async def _render(pct: float) -> None:
        state = pending_dl.transfer_state or ""
        queued = "queued" in state.lower()
        headline = (
            self.t(pending_dl.chat_id, "download_queued_headline", chip=chip)
            if queued
            else self.t(pending_dl.chat_id, "download_headline", chip=chip, pct=f"{pct:.0f}")
        )
        extra = self.t(pending_dl.chat_id, "download_queued_extra") if queued else progress_bar(pct)
        await safe_edit(
            status_msg,
            self.t(
                pending_dl.chat_id,
                "download_progress",
                headline=headline,
                extra=extra,
                file=md_code_safe(result.basename),
            ),
            parse_mode=ParseMode.MARKDOWN,
        )

    return _render


def _retry_keyboard(self, chat_id: int, result_index: int, dl_id: str, search_id: str | None = None):
    locale = self.locale(chat_id)
    if self._has_next_result(chat_id, result_index, search_id=search_id):
        return build_retry_next_keyboard(dl_id, locale=locale)
    return build_retry_keyboard(dl_id, locale=locale)


async def _report_enqueue_failure(
    self, status_msg, chat_id: int, result: SearchResult, result_index: int, dl_id: str, search_id: str | None = None
):
    await safe_edit(
        status_msg,
        self.t(chat_id, "enqueue_failed", user=md_code_safe(result.username)),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_retry_keyboard(self, chat_id, result_index, dl_id, search_id),
    )


async def _report_download_failure(
    self,
    status_msg,
    chat_id: int,
    result: SearchResult,
    result_index: int,
    dl_id: str,
    state: str,
    search_id: str | None = None,
):
    await safe_edit(
        status_msg,
        self.t(chat_id, "download_failed", state=state, file=md_code_safe(result.basename)),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_retry_keyboard(self, chat_id, result_index, dl_id, search_id),
    )


async def _build_quality_line(self, chat_id: int, track: TrackInfo, result: SearchResult, source_path: str) -> str:
    quality_line = f"{result.quality_display}  ·  {result.duration_display}"
    locale = self.locale(chat_id)
    reasons = format_result_reasons(track, result, locale=locale)
    if reasons:
        quality_line += f"\n{reasons}"

    if result.extension != "flac":
        return quality_line
    verdict = await self._analyze_flac(source_path)
    if verdict:
        quality_line += f"\n{format_flac_verdict(verdict, locale=locale)}"
    return quality_line


async def _deliver_preview(
    self,
    context,
    chat_id: int,
    track: TrackInfo,
    result: SearchResult,
    source_path: str,
    quality_line: str,
    label: str,
    chip: str,
    dl_id: str,
    result_index: int,
    can_save: bool,
    search_id: str | None = None,
    origin_id: int | None = None,
) -> bool:
    """Send the downloaded audio (or a preview for over-limit files). Returns delivery success."""
    file_size = os.path.getsize(source_path) if os.path.isfile(source_path) else 0
    markup = (
        build_approve_keyboard(
            dl_id,
            has_next=self._has_next_result(chat_id, result_index, search_id=search_id),
            locale=self.locale(chat_id),
        )
        if can_save
        else None
    )

    if file_size > self.config.telegram_file_limit:
        delivered = await self._send_large_file(
            context,
            chat_id,
            track,
            result,
            source_path,
            file_size,
            quality_line,
            label,
            dl_id,
            reply_markup=markup,
            can_save=can_save,
            chip=chip,
            reply_to_message_id=origin_id,
        )
        await _after_preview(self, context, chat_id, dl_id, search_id, result_index, delivered)
        return delivered

    caption = self.t(
        chat_id,
        "caption_save" if can_save else "caption_sent",
        chip=chip,
        quality=quality_line,
    )
    sent = await send_audio_or_document(
        context,
        chat_id,
        source_path,
        filename=self.processor.build_filename(track.artist, track.title, result.extension),
        title=track.title,
        performer=track.artist,
        duration=track.duration_secs,
        caption=caption,
        reply_markup=markup,
        reply_to_message_id=origin_id,
    )
    remember_approval_message(self, dl_id, sent.message_id)
    await _after_preview(self, context, chat_id, dl_id, search_id, result_index, True)
    return True


async def _after_preview(
    self, context, chat_id: int, dl_id: str, search_id: str | None, result_index: int, delivered: bool
) -> None:
    """Collapse the progress text and mark the results card once a preview exists."""
    pending_dl = self.downloads.get(dl_id)
    if pending_dl and pending_dl.status_message_id and pending_dl.status_message_id != pending_dl.origin_message_id:
        await collapse_status_message(
            context.bot,
            chat_id,
            pending_dl.status_message_id,
            fallback=self.t(chat_id, "status_preview_below"),
        )
        pending_dl.status_message_id = None
    if delivered:
        await self._set_results_pick_state(context, search_id, result_index, "awaiting")
    else:
        await self._set_results_pick_state(context, search_id, result_index, "failed")


async def _forget_local_copy(
    self,
    pending_dl: PendingDownload,
    track: TrackInfo,
    result: SearchResult,
    chat_id: int,
    status: str = "delivered",
):
    """Send-only users: drop the local file and slskd transfer after Telegram delivery."""
    for key, value in list(self.downloads.items()):
        if value is pending_dl:
            del self.downloads[key]
            break
    await self._cleanup_download_artifacts(pending_dl)
    await self._add_history(track, result, status, chat_id=chat_id)
