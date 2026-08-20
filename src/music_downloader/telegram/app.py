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
    TypeHandler,
    filters,
)

from music_downloader.catalog.playlist import PlaylistResolver
from music_downloader.catalog.soundcloud import SoundCloudResolver
from music_downloader.catalog.spotify import SpotifyResolver
from music_downloader.catalog.track import TrackInfo
from music_downloader.history.store import HistoryRepository
from music_downloader.i18n.catalog import gettext as _
from music_downloader.i18n.store import LocaleStore
from music_downloader.library.files import FileProcessor
from music_downloader.playlist_import.store import ImportRepository
from music_downloader.records.database import Database
from music_downloader.settings.config import Config
from music_downloader.soulseek.client import SlskdClient
from music_downloader.soulseek.query import parse_query_artist_title
from music_downloader.soulseek.result import SearchResult
from music_downloader.soulseek.scoring import ResultScorer
from music_downloader.telegram import commands, download_flow, import_flow, language, search_flow
from music_downloader.telegram.messages import format_search_results, format_spotify_results, safe_query_edit
from music_downloader.telegram.session import ChatSession

logger = logging.getLogger(__name__)


class MusicBot:
    """Coordinates catalog lookup, Soulseek search, library import, and Telegram UX."""

    def __init__(self, config: Config):
        self.config = config
        self.spotify = SpotifyResolver(config.spotify_client_id, config.spotify_client_secret)
        self.soundcloud = SoundCloudResolver()
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
        self._auto_overrides = session._auto_overrides
        self._quality_overrides = session._quality_overrides
        self._session = session

        self.db = Database(f"{config.data_dir}/importer.db")
        self.history_repo = HistoryRepository(self.db)
        self.import_repo = ImportRepository(self.db)
        self.locale_store = LocaleStore(self.db)
        self.playlist_resolver = PlaylistResolver(self.spotify)

    def is_auto(self, chat_id: int) -> bool:
        """Effective auto-download mode for a chat: per-chat toggle, else config default."""
        return self._auto_overrides.get(chat_id, self.auto_mode)

    def quality_pref(self, chat_id: int) -> str:
        """Effective audio quality preference for a chat: per-chat toggle, else config default."""
        return self._quality_overrides.get(chat_id, self.config.quality_preference)

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
            await update.message.reply_text(_("You are not authorized to use this bot."))
            return False
        return True

    async def _check_library_auth(self, update: Update) -> bool:
        if not await self._check_auth(update):
            return False
        if not self._can_save_library(update.effective_user.id):
            await update.message.reply_text(
                _(
                    "You can search and download files, but only library users can save to the music library or import playlists."
                )
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
        await self._remove_download_file(dl.source_path)

    async def _remove_download_file(self, source_path: str | None) -> None:
        """Delete a downloaded file, falling back to slskd remote file management.

        When DOWNLOAD_DIR is mounted read-only the local delete fails and the
        original file would linger next to the renamed library copy.  In that
        case ask slskd (which owns the directory) to delete it instead —
        requires SLSKD_REMOTE_FILE_MANAGEMENT=true on the slskd side.
        """
        if not source_path:
            return
        if self.processor.cleanup_download(source_path) or not os.path.isfile(source_path):
            return

        rel_path = self.processor.relative_download_path(source_path)
        if not rel_path:
            logger.warning("Download outside DOWNLOAD_DIR, cannot delete via slskd: %s", source_path)
            return

        deleted = await asyncio.to_thread(self.slskd.delete_downloaded_file, rel_path)
        if not deleted:
            logger.warning(
                "Could not delete download %s locally or via slskd; the original file will remain. "
                "Mount DOWNLOAD_DIR read-write or enable remote file management on slskd "
                "(SLSKD_REMOTE_FILE_MANAGEMENT=true).",
                source_path,
            )
            return

        # Mirror local cleanup: drop the now-empty per-user directory.
        parent = os.path.dirname(source_path)
        rel_parent = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
        if rel_parent and os.path.isdir(parent) and not os.listdir(parent):
            await asyncio.to_thread(self.slskd.delete_downloaded_directory, rel_parent)

    def _is_stale(self, chat_id: int, generation: int) -> bool:
        return self._session.is_stale(chat_id, generation)

    def _track_task(self, chat_id: int, task: asyncio.Task):
        self._session.track_task(chat_id, task)

    def _next_dl_id(self) -> str:
        self._dl_counter += 1
        self._session._dl_counter = self._dl_counter
        return str(self._dl_counter)

    def _rank_responses(
        self,
        raw_responses,
        track: TrackInfo,
        max_duration_diff: int | None = None,
        quality_preference: str | None = None,
    ) -> tuple[list[SearchResult], bool]:
        """Parse raw slskd responses and rank: try FLAC first, fall back to all audio."""
        score_kwargs = {"max_duration_diff": max_duration_diff} if max_duration_diff else {}
        if quality_preference:
            score_kwargs["quality_preference"] = quality_preference
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
            "if": self._handle_import_callback,
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
            self._auto_overrides[chat_id] = data == "auto:on"
            mode_str = _("ON") if self.is_auto(chat_id) else _("OFF")
            await safe_query_edit(
                query,
                _("Auto-download mode: *{mode}*").format(mode=mode_str),
                parse_mode="Markdown",
            )
            return

        if data.startswith("qp:"):
            pref = data.split(":", 1)[1]
            if pref in ("cd", "hires"):
                self._quality_overrides[chat_id] = pref
            label = _("CD quality (16/44.1)") if self.quality_pref(chat_id) == "cd" else _("Hi-Res (24-bit)")
            await safe_query_edit(
                query,
                _("Audio quality preference: *{label}*").format(label=label),
                parse_mode="Markdown",
            )
            return

    cmd_start = commands.cmd_start
    cmd_help = commands.cmd_help
    cmd_auto = commands.cmd_auto
    cmd_quality = commands.cmd_quality
    cmd_undo = commands.cmd_undo
    cmd_status = commands.cmd_status
    cmd_history = commands.cmd_history
    cmd_lang = language.cmd_lang
    cmd_import = import_flow.cmd_import
    cmd_cancel = import_flow.cmd_cancel
    ensure_locale = language.ensure_locale

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
    _handle_import_retry_failed = import_flow.handle_import_retry_failed
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
        await language.register_bot_commands(application)
        await bot.resume_stale_imports(application)

    app = Application.builder().token(config.telegram_bot_token).post_init(_post_init).build()
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
