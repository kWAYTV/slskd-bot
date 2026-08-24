"""Telegram application composition: MusicBot wiring + handler registration."""

from __future__ import annotations

import asyncio
import logging

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from music_downloader.catalog.playlist import PlaylistResolver
from music_downloader.catalog.spotify import SpotifyResolver
from music_downloader.history.store import HistoryRepository
from music_downloader.library.files import FileProcessor
from music_downloader.playlist_import.store import ImportRepository
from music_downloader.records.database import Database
from music_downloader.records.prefs import ChatPrefsRepository
from music_downloader.settings.config import Config
from music_downloader.soulseek.client import SlskdClient
from music_downloader.soulseek.scoring import ResultScorer
from music_downloader.telegram.commands import activity, basics, preferences
from music_downloader.telegram.core import access, cleanup, routing, ttl
from music_downloader.telegram.core.session import ChatSession
from music_downloader.telegram.download import approval, delivery, retry, run, selection, transfer
from music_downloader.telegram.playlist_import import callbacks as import_callbacks
from music_downloader.telegram.playlist_import import command as import_command
from music_downloader.telegram.playlist_import import download as import_download
from music_downloader.telegram.playlist_import import queue as import_queue
from music_downloader.telegram.playlist_import import resume as import_resume
from music_downloader.telegram.playlist_import import search as import_search
from music_downloader.telegram.search import direct, results, soulseek, spotify, text
from music_downloader.telegram.ui.editing import edit_approval_message

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
        # Chat state lives in the session; attributes below alias its dicts so
        # conversation modules and tests can address them directly on the bot.
        session = ChatSession()
        self._session = session
        self.pending = session.pending
        self.downloads = session.downloads
        self._spotify_candidates = session._spotify_candidates
        self._spotify_page = session._spotify_page
        self._chat_generation = session._chat_generation
        self._active_tasks = session._active_tasks
        self._active_import = session._active_import
        self._import_pending = session._import_pending
        self._import_status_msg = session._import_status_msg
        self._quality_overrides = session._quality_overrides
        self._download_sem = asyncio.Semaphore(config.max_concurrent_downloads)

        self.db = Database(f"{config.data_dir}/importer.db")
        self.history_repo = HistoryRepository(self.db)
        self.import_repo = ImportRepository(self.db)
        self.prefs_repo = ChatPrefsRepository(self.db)
        self._quality_overrides.update(self.prefs_repo.load_all_quality())
        self.playlist_resolver = PlaylistResolver(self.spotify)

    # --- per-chat preferences -------------------------------------------------

    def quality_pref(self, chat_id: int) -> str:
        """Effective audio quality preference for a chat: per-chat toggle, else config default."""
        return self._quality_overrides.get(chat_id, self.config.quality_preference)

    # --- session delegation ----------------------------------------------------

    def _is_stale(self, chat_id: int, generation: int) -> bool:
        return self._session.is_stale(chat_id, generation)

    def _track_task(self, chat_id: int, task: asyncio.Task):
        self._session.track_task(chat_id, task)

    def _next_dl_id(self) -> str:
        return self._session.next_dl_id()

    # --- conversation handlers, composed from feature modules ------------------

    handle_callback = routing.handle_callback

    _is_authorized = access.is_authorized
    _can_save_library = access.can_save_library
    _check_auth = access.check_auth
    _check_library_auth = access.check_library_auth

    _cancel_chat_operations = cleanup.cancel_chat_operations
    _cleanup_download_artifacts = cleanup.cleanup_download_artifacts
    _remove_download_file = cleanup.remove_download_file
    expire_stale_approvals = ttl.expire_stale_approvals

    cmd_start = basics.cmd_start
    cmd_quality = preferences.cmd_quality
    cmd_undo = activity.cmd_undo
    cmd_status = activity.cmd_status
    cmd_history = activity.cmd_history
    cmd_stats = activity.cmd_stats
    cmd_cancel = activity.cmd_cancel
    _handle_history_undo = activity.handle_history_undo
    cmd_import = import_command.cmd_import

    handle_text = text.handle_text
    _do_search = spotify.do_search
    _do_slskd_search = soulseek.do_slskd_search
    _search_with_fallbacks = soulseek.search_with_fallbacks
    _handle_spotify_page = spotify.handle_spotify_page
    _handle_spotify_selection = spotify.handle_spotify_selection
    _handle_results_page = results.handle_results_page
    _handle_direct_search = direct.handle_direct_search
    _do_direct_slskd_search = direct.do_direct_slskd_search

    _handle_download_selection = selection.handle_download_selection
    _has_next_result = selection.has_next_result
    _do_download = run.do_download
    _send_large_file = delivery.send_large_file
    _handle_approval = approval.handle_approval
    _dismiss_other_downloads = approval.dismiss_other_downloads
    _edit_approval_message = staticmethod(edit_approval_message)
    _handle_retry = retry.handle_retry
    _handle_next_result = retry.handle_next_result
    _analyze_flac = staticmethod(delivery.analyze_flac_async)
    _convert_to_ogg = staticmethod(delivery.convert_to_ogg_async)
    _create_preview = staticmethod(delivery.create_preview_async)
    _embed_spotify_artwork = delivery.embed_spotify_artwork
    _add_history = transfer.add_history

    _handle_import_callback = import_callbacks.handle_import_callback
    _handle_import_approve = import_callbacks.handle_import_approve
    _handle_import_retry = import_callbacks.handle_import_retry
    _handle_import_retry_failed = import_callbacks.handle_import_retry_failed
    _process_next_import_track = import_queue.process_next_import_track
    _do_import_slskd_search = import_search.do_import_slskd_search
    _do_import_download = import_download.do_import_download
    resume_stale_imports = import_resume.resume_stale_imports
    _resume_import_job = import_resume.resume_import_job


def create_bot(config: Config) -> Application:
    """Create and configure the Telegram bot application."""
    bot = MusicBot(config)

    async def _post_init(application: Application) -> None:
        application.bot_data["music_bot"] = bot
        await basics.register_bot_commands(application)
        await bot.resume_stale_imports(application)
        application.create_task(ttl.run_approval_ttl_loop(bot, application))

    builder = Application.builder().token(config.telegram_bot_token).post_init(_post_init)
    if config.telegram_api_base_url:
        # Self-hosted Bot API server: 2000 MB uploads instead of the cloud 50 MB.
        builder = (
            builder.base_url(f"{config.telegram_api_base_url}/bot")
            .base_file_url(f"{config.telegram_api_base_url}/file/bot")
            .local_mode(True)
        )
    app = builder.build()
    app.bot_data["music_bot"] = bot

    app.add_handler(CommandHandler(["start", "help"], bot.cmd_start))
    app.add_handler(CommandHandler("quality", bot.cmd_quality))
    app.add_handler(CommandHandler("undo", bot.cmd_undo))
    app.add_handler(CommandHandler("status", bot.cmd_status))
    app.add_handler(CommandHandler("history", bot.cmd_history))
    app.add_handler(CommandHandler("stats", bot.cmd_stats))
    app.add_handler(CommandHandler("import", bot.cmd_import))
    app.add_handler(CommandHandler("cancel", bot.cmd_cancel))
    app.add_handler(CallbackQueryHandler(bot.handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text))
    app.add_error_handler(_on_error)

    logger.info("Telegram bot configured (local_api=%s)", bool(config.telegram_api_base_url))
    return app


async def _on_error(update: object, context) -> None:
    """Log unhandled exceptions from conversation handlers."""
    logger.error("Unhandled Telegram error: %s", context.error, exc_info=context.error)
