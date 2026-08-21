"""Telegram application composition: MusicBot wiring + handler registration."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from music_downloader.catalog.playlist import PlaylistResolver
from music_downloader.catalog.soundcloud_resolver import SoundCloudResolver
from music_downloader.catalog.spotify import SpotifyResolver
from music_downloader.catalog.track import TrackInfo
from music_downloader.history.store import HistoryRepository
from music_downloader.i18n.store import LocaleStore
from music_downloader.library.files import FileProcessor
from music_downloader.playlist_import.store import ImportRepository
from music_downloader.records.database import Database
from music_downloader.settings.config import Config
from music_downloader.soulseek.client import SlskdClient
from music_downloader.soulseek.query import parse_query_artist_title
from music_downloader.soulseek.ranking import rank_responses
from music_downloader.soulseek.result import SearchResult
from music_downloader.soulseek.scoring import ResultScorer
from music_downloader.telegram.commands import activity, basics, language, preferences
from music_downloader.telegram.core import access, cleanup, routing
from music_downloader.telegram.core.session import ChatSession
from music_downloader.telegram.download import approval, delivery, media, retry, run, selection
from music_downloader.telegram.download import history as download_history
from music_downloader.telegram.playlist_import import callbacks as import_callbacks
from music_downloader.telegram.playlist_import import command as import_command
from music_downloader.telegram.playlist_import import download as import_download
from music_downloader.telegram.playlist_import import queue as import_queue
from music_downloader.telegram.playlist_import import resume as import_resume
from music_downloader.telegram.playlist_import import search as import_search
from music_downloader.telegram.search import direct, duplicates, results, soulseek, spotify, text
from music_downloader.telegram.ui.editing import edit_approval_message
from music_downloader.telegram.ui.formatting import format_search_results, format_spotify_results

logger = logging.getLogger(__name__)


class MusicBot:
    """Coordinates catalog lookup, Soulseek search, library import, and Telegram UX."""

    def __init__(self, config: Config):
        self.config = config
        self.spotify = SpotifyResolver(config.spotify_client_id, config.spotify_client_secret)
        self.soundcloud = SoundCloudResolver(
            client_id=config.soundcloud_client_id,
            client_secret=config.soundcloud_client_secret,
        )
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
        self.auto_mode = config.auto_mode  # process-wide default; per-chat overrides win

        # Chat state lives in the session; attributes below alias its dicts so
        # conversation modules and tests can address them directly on the bot.
        session = ChatSession()
        self._session = session
        self.pending = session.pending
        self.downloads = session.downloads
        self._spotify_candidates = session._spotify_candidates
        self._spotify_page = session._spotify_page
        self._awaiting_direct_metadata = session._awaiting_direct_metadata
        self._chat_generation = session._chat_generation
        self._active_tasks = session._active_tasks
        self._active_import = session._active_import
        self._import_pending = session._import_pending
        self._auto_overrides = session._auto_overrides
        self._quality_overrides = session._quality_overrides

        self.db = Database(f"{config.data_dir}/importer.db")
        self.history_repo = HistoryRepository(self.db)
        self.import_repo = ImportRepository(self.db)
        self.locale_store = LocaleStore(self.db)
        self.playlist_resolver = PlaylistResolver(self.spotify)

    # --- per-chat preferences -------------------------------------------------

    def is_auto(self, chat_id: int) -> bool:
        """Effective auto-download mode for a chat: per-chat toggle, else config default."""
        return self._auto_overrides.get(chat_id, self.auto_mode)

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

    # --- domain shims (bound here so conversation modules share one entry) -----

    def _rank_responses(
        self,
        raw_responses,
        track: TrackInfo,
        max_duration_diff: int | None = None,
        quality_preference: str | None = None,
    ) -> tuple[list[SearchResult], bool]:
        """Parse raw slskd responses and rank: try FLAC first, fall back to all audio."""
        return rank_responses(
            raw_responses,
            track,
            self.scorer,
            max_duration_diff=max_duration_diff,
            quality_preference=quality_preference,
        )

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

    # --- conversation handlers, composed from feature modules ------------------

    handle_callback = routing.handle_callback

    _is_authorized = access.is_authorized
    _can_save_library = access.can_save_library
    _check_auth = access.check_auth
    _check_library_auth = access.check_library_auth

    _cancel_chat_operations = cleanup.cancel_chat_operations
    _cleanup_download_artifacts = cleanup.cleanup_download_artifacts
    _remove_download_file = cleanup.remove_download_file

    cmd_start = basics.cmd_start
    cmd_help = basics.cmd_help
    cmd_auto = preferences.cmd_auto
    cmd_quality = preferences.cmd_quality
    cmd_undo = activity.cmd_undo
    cmd_status = activity.cmd_status
    cmd_history = activity.cmd_history
    cmd_cancel = activity.cmd_cancel
    cmd_lang = language.cmd_lang
    cmd_import = import_command.cmd_import
    ensure_locale = language.ensure_locale

    handle_text = text.handle_text
    _do_search = spotify.do_search
    _do_slskd_search = soulseek.do_slskd_search
    _search_with_fallbacks = soulseek.search_with_fallbacks
    _handle_duplicate_response = duplicates.handle_duplicate_response
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
    _analyze_flac = staticmethod(media.analyze_flac_async)
    _convert_to_ogg = staticmethod(media.convert_to_ogg_async)
    _create_preview = staticmethod(media.create_preview_async)
    _embed_spotify_artwork = media.embed_spotify_artwork
    _add_history = download_history.add_history

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
        await language.register_bot_commands(application)
        await bot.resume_stale_imports(application)

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

    app.add_handler(TypeHandler(Update, bot.ensure_locale), group=-1)
    app.add_handler(CommandHandler("start", bot.cmd_start))
    app.add_handler(CommandHandler("help", bot.cmd_help))
    app.add_handler(CommandHandler("auto", bot.cmd_auto))
    app.add_handler(CommandHandler("quality", bot.cmd_quality))
    app.add_handler(CommandHandler("undo", bot.cmd_undo))
    app.add_handler(CommandHandler("status", bot.cmd_status))
    app.add_handler(CommandHandler("history", bot.cmd_history))
    app.add_handler(CommandHandler(["lang", "language"], bot.cmd_lang))
    app.add_handler(CommandHandler("import", bot.cmd_import))
    app.add_handler(CommandHandler("cancel", bot.cmd_cancel))
    app.add_handler(CallbackQueryHandler(bot.handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text))

    logger.info("Telegram bot configured")
    return app
