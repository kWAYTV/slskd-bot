"""Telegram application composition: MusicBot + handler registration."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from music_downloader.catalog.playlist import PlaylistResolver
from music_downloader.catalog.spotify import SpotifyResolver
from music_downloader.catalog.track import TrackInfo
from music_downloader.history.store import HistoryRepository
from music_downloader.library.files import FileProcessor
from music_downloader.playlist_import.store import ImportRepository
from music_downloader.records.database import Database
from music_downloader.settings.config import Config
from music_downloader.soulseek.client import SlskdClient
from music_downloader.soulseek.query import parse_query_artist_title
from music_downloader.soulseek.result import SearchResult
from music_downloader.soulseek.scoring import ResultScorer
from music_downloader.telegram import commands, download_flow, import_flow, search_flow
from music_downloader.telegram.messages import format_search_results, format_spotify_results
from music_downloader.telegram.session import ChatSession

logger = logging.getLogger(__name__)


class MusicBot:
    """Coordinates catalog lookup, Soulseek search, library import, and Telegram UX."""

    def __init__(self, config: Config):
        self.config = config
        self.spotify = SpotifyResolver(config.spotify_client_id, config.spotify_client_secret)
        self.slskd = SlskdClient(config.slskd_host, config.slskd_api_key)
        self.scorer = ResultScorer(
            duration_tolerance_secs=config.duration_tolerance_secs,
            exclude_keywords=config.exclude_keywords,
        )
        self.processor = FileProcessor(
            download_dir=config.download_dir,
            output_dir=config.output_dir,
            filename_template=config.filename_template,
        )
        self.auto_mode = config.auto_mode

        session = ChatSession()
        self.pending = session.pending
        self.downloads = session.downloads
        self._dl_counter = 0
        self._spotify_candidates = session._spotify_candidates
        self._spotify_page = session._spotify_page
        self._awaiting_direct_metadata = session._awaiting_direct_metadata
        self._chat_generation = session._chat_generation
        self._active_tasks = session._active_tasks
        self._active_import = session._active_import
        self._import_pending = session._import_pending
        self._session = session

        self.db = Database(f"{config.data_dir}/importer.db")
        self.history_repo = HistoryRepository(self.db)
        self.import_repo = ImportRepository(self.db)
        self.playlist_resolver = PlaylistResolver(self.spotify)

    def _is_authorized(self, user_id: int) -> bool:
        if not self.config.telegram_allowed_users:
            return False
        return user_id in self.config.telegram_allowed_users

    def _can_save_library(self, user_id: int | None) -> bool:
        """Library save is allowed for all authorized users unless TELEGRAM_LIBRARY_USERS is set."""
        library_users = getattr(self.config, "telegram_library_users", None)
        if not isinstance(library_users, (set, frozenset)):
            return True
        if not library_users:
            return True
        if user_id is None:
            return False
        return user_id in library_users

    async def _check_auth(self, update: Update) -> bool:
        if not self._is_authorized(update.effective_user.id):
            await update.message.reply_text("You are not authorized to use this bot.")
            return False
        return True

    async def _check_library_auth(self, update: Update) -> bool:
        if not await self._check_auth(update):
            return False
        if not self._can_save_library(update.effective_user.id):
            await update.message.reply_text(
                "You can search and download files, but only library users can save to the music library or import playlists."
            )
            return False
        return True

    async def _cancel_chat_operations(self, chat_id: int) -> bool:
        had_work, stale = self._session.cancel_chat_operations(chat_id)
        for dl in stale:
            await self._cleanup_download_artifacts(dl)
        return had_work

    async def _cleanup_download_artifacts(self, dl) -> None:
        """Cancel the slskd transfer and delete any local file for a pending download."""
        result = dl.result
        try:
            await asyncio.to_thread(
                self.slskd.cancel_transfer,
                result.username,
                result.filename,
                dl.transfer_id,
            )
        except Exception:
            logger.debug("slskd transfer cancel failed for %s", result.basename, exc_info=True)
        if dl.source_path and os.path.isfile(dl.source_path):
            with contextlib.suppress(OSError):
                os.remove(dl.source_path)
                logger.info("Deleted cancelled download: %s", dl.source_path)

    def _is_stale(self, chat_id: int, generation: int) -> bool:
        return self._session.is_stale(chat_id, generation)

    def _track_task(self, chat_id: int, task: asyncio.Task):
        self._session.track_task(chat_id, task)

    def _next_dl_id(self) -> str:
        self._dl_counter += 1
        self._session._dl_counter = self._dl_counter
        return str(self._dl_counter)

    def _rank_responses(
        self, raw_responses, track: TrackInfo, max_duration_diff: int | None = None
    ) -> tuple[list[SearchResult], bool]:
        """Parse raw slskd responses and rank: try FLAC first, fall back to all audio."""
        score_kwargs = {"max_duration_diff": max_duration_diff} if max_duration_diff else {}
        flac_results = self.slskd.parse_results(raw_responses, flac_only=True)
        ranked = self.scorer.score_results(flac_results, track, **score_kwargs)
        if ranked:
            return ranked, False
        all_audio = self.slskd.parse_results(raw_responses, flac_only=False)
        ranked = self.scorer.score_results(all_audio, track, **score_kwargs)
        return ranked, bool(ranked)

    @staticmethod
    def _format_spotify_results(tracks: list[TrackInfo], page: int = 0, page_size: int = 5) -> str:
        return format_spotify_results(tracks, page=page, page_size=page_size)

    def _format_results(
        self,
        track: TrackInfo,
        results: list[SearchResult],
        is_fallback: bool = False,
        page: int = 0,
        page_size: int = 10,
    ) -> str:
        return format_search_results(track, results, is_fallback=is_fallback, page=page, page_size=page_size)

    @staticmethod
    def _parse_query_artist_title(query: str) -> tuple[str, str]:
        return parse_query_artist_title(query)

    async def _add_history(self, track: TrackInfo, result: SearchResult, status: str, chat_id: int | None = None):
        await asyncio.to_thread(
            self.history_repo.add,
            artist=track.artist,
            title=track.title,
            album=track.album,
            filename=f"{track.artist} - {track.title}.{result.extension}",
            source_user=result.username,
            remote_path=result.filename,
            status=status,
            duration_secs=track.duration_secs,
            file_size=result.size,
            chat_id=chat_id,
            spotify_url=track.spotify_url,
        )

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard button presses."""
        query = update.callback_query
        with contextlib.suppress(BadRequest):
            await query.answer()

        if not self._is_authorized(query.from_user.id):
            return

        chat_id = update.effective_chat.id
        data = query.data

        prefix = data.split(":", 1)[0]
        handler = {
            "direct": self._handle_direct_search,
            "ic": self._handle_import_callback,
            "ix": self._handle_import_callback,
            "ia": self._handle_import_callback,
            "ir": self._handle_import_callback,
            "is": self._handle_import_callback,
            "iy": self._handle_import_callback,
            "retry": self._handle_retry,
            "next": self._handle_next_result,
            "dup": self._handle_duplicate_response,
            "sp_page": self._handle_spotify_page,
            "sp": self._handle_spotify_selection,
            "dl_page": self._handle_results_page,
            "dl": self._handle_download_selection,
            "approve": self._handle_approval,
            "reject": self._handle_approval,
        }.get(prefix)

        if handler:
            await handler(update, context, chat_id, data)
            return

        if data.startswith("auto:"):
            self.auto_mode = data == "auto:on"
            mode_str = "ON" if self.auto_mode else "OFF"
            await query.edit_message_text(
                f"Auto-download mode: *{mode_str}*",
                parse_mode="Markdown",
            )
            return

    cmd_start = commands.cmd_start
    cmd_help = commands.cmd_help
    cmd_auto = commands.cmd_auto
    cmd_status = commands.cmd_status
    cmd_history = commands.cmd_history
    cmd_import = import_flow.cmd_import
    cmd_cancel = import_flow.cmd_cancel

    handle_text = search_flow.handle_text
    _do_search = search_flow.do_search
    _do_slskd_search = search_flow.do_slskd_search
    _search_with_fallbacks = search_flow.search_with_fallbacks
    _handle_duplicate_response = search_flow.handle_duplicate_response
    _handle_spotify_page = search_flow.handle_spotify_page
    _handle_spotify_selection = search_flow.handle_spotify_selection
    _handle_results_page = search_flow.handle_results_page
    _handle_direct_search = search_flow.handle_direct_search
    _do_direct_slskd_search = search_flow.do_direct_slskd_search

    _handle_download_selection = download_flow.handle_download_selection
    _has_next_result = download_flow.has_next_result
    _do_download = download_flow.do_download
    _send_large_file = download_flow.send_large_file
    _handle_approval = download_flow.handle_approval
    _dismiss_other_downloads = download_flow.dismiss_other_downloads
    _edit_approval_message = staticmethod(download_flow.edit_approval_message)
    _handle_retry = download_flow.handle_retry
    _handle_next_result = download_flow.handle_next_result
    _analyze_flac = staticmethod(download_flow.analyze_flac_async)
    _convert_to_ogg = staticmethod(download_flow.convert_to_ogg_async)
    _create_preview = staticmethod(download_flow.create_preview_async)
    _embed_spotify_artwork = download_flow.embed_spotify_artwork

    _handle_import_callback = import_flow.handle_import_callback
    _handle_import_approve = import_flow.handle_import_approve
    _handle_import_retry = import_flow.handle_import_retry
    _process_next_import_track = import_flow.process_next_import_track
    _do_import_slskd_search = import_flow.do_import_slskd_search
    _do_import_download = import_flow.do_import_download
    resume_stale_imports = import_flow.resume_stale_imports
    _resume_import_job = import_flow.resume_import_job


def create_bot(config: Config) -> Application:
    """Create and configure the Telegram bot application."""
    bot = MusicBot(config)

    async def _post_init(application: Application) -> None:
        application.bot_data["music_bot"] = bot
        await bot.resume_stale_imports(application)

    app = Application.builder().token(config.telegram_bot_token).post_init(_post_init).build()
    app.bot_data["music_bot"] = bot

    app.add_handler(CommandHandler("start", bot.cmd_start))
    app.add_handler(CommandHandler("help", bot.cmd_help))
    app.add_handler(CommandHandler("auto", bot.cmd_auto))
    app.add_handler(CommandHandler("status", bot.cmd_status))
    app.add_handler(CommandHandler("history", bot.cmd_history))
    app.add_handler(CommandHandler("import", bot.cmd_import))
    app.add_handler(CommandHandler("cancel", bot.cmd_cancel))
    app.add_handler(CallbackQueryHandler(bot.handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text))

    logger.info("Telegram bot configured")
    return app
