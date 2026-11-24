"""Telegram application composition: MusicBot wiring + handler registration."""

from __future__ import annotations

import logging

from telegram import Bot
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from slskd_importer.catalog.musicbrainz import MusicBrainzClient
from slskd_importer.catalog.spotify import SpotifyResolver
from slskd_importer.history.store import HistoryRepository
from slskd_importer.library.files import FileProcessor
from slskd_importer.library.index import LibraryIndex
from slskd_importer.queue.copies import CopyFinder
from slskd_importer.queue.pipeline import ItemPipeline
from slskd_importer.queue.runner import QueueRunner
from slskd_importer.queue.shelf import LibraryShelf
from slskd_importer.queue.store import QueueRepository
from slskd_importer.records.database import Database
from slskd_importer.records.prefs import ChatPrefsRepository
from slskd_importer.settings.config import Config
from slskd_importer.soulseek.client import SlskdClient
from slskd_importer.soulseek.scoring import ResultScorer
from slskd_importer.sweep import LibrarySweep
from slskd_importer.telegram.card import callbacks as card_callbacks
from slskd_importer.telegram.card.board import CardBoard
from slskd_importer.telegram.commands import basics, cancel, check, history, preferences, stats, status, undo
from slskd_importer.telegram.core import access, routing
from slskd_importer.telegram.delivery import handoff
from slskd_importer.telegram.i18n import DEFAULT_LOCALE, normalize_locale
from slskd_importer.telegram.i18n import t as translate
from slskd_importer.telegram.intake import message as intake
from slskd_importer.telegram.library_sweep import callbacks as sweep_callbacks
from slskd_importer.telegram.library_sweep import command as sweep_command
from slskd_importer.telegram.library_sweep import lifecycle as sweep_lifecycle

logger = logging.getLogger(__name__)


class MusicBot:
    """Coordinates catalog lookup, the download queue, the library, and Telegram UX."""

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

        self.db = Database(f"{config.data_dir}/importer.db")
        self.history_repo = HistoryRepository(self.db)
        self.prefs_repo = ChatPrefsRepository(self.db)
        self._locales: dict[int, str] = self.prefs_repo.load_all_locales()

        self.queue_store = QueueRepository(self.db)
        # Raw downloads are not part of the collection, even when their folder sits inside it.
        collection = LibraryIndex(config.library_sweep_dir, exclude=(config.download_dir,))
        self.shelf = LibraryShelf(self.processor, self.spotify, self.history_repo, collection)
        pipeline = ItemPipeline(
            config=config,
            spotify=self.spotify,
            slskd=self.slskd,
            processor=self.processor,
            store=self.queue_store,
            finder=CopyFinder(config, self.slskd, self.scorer),
            shelf=self.shelf,
        )
        pipeline.deliver = self._deliver_copy
        self.runner = QueueRunner(self.queue_store, pipeline, workers=config.max_concurrent_downloads)
        self.cards = CardBoard(self.runner, self.locale, page_size=config.max_results)
        self.runner.on_change = self.cards.request
        # Set once the Application exists; cards and deliveries are sent outside any update.
        self.telegram: Bot | None = None

        self.musicbrainz = MusicBrainzClient()
        self.sweep = LibrarySweep(
            config,
            self.db,
            self.spotify,
            self.musicbrainz,
            self.slskd,
            self.scorer,
            self.processor,
        )

    def attach(self, telegram: Bot) -> None:
        self.telegram = telegram
        self.cards.telegram = telegram

    # --- per-chat preferences -------------------------------------------------

    def locale(self, chat_id: int) -> str:
        """Persisted locale for a chat, or English if the user has not chosen one."""
        return self._locales.get(chat_id, DEFAULT_LOCALE)

    def has_locale(self, chat_id: int) -> bool:
        return chat_id in self._locales

    def t(self, chat_id: int, key: str, **kwargs: object) -> str:
        return translate(self.locale(chat_id), key, **kwargs)

    def set_locale(self, chat_id: int, locale: str) -> bool:
        """Remember a chat locale. Returns True when this is the first saved locale."""
        first = chat_id not in self._locales
        self._locales[chat_id] = normalize_locale(locale)
        return first

    # --- conversation handlers, composed from feature modules ------------------

    handle_callback = routing.handle_callback

    _is_authorized = access.is_authorized
    _can_save_library = access.can_save_library
    _check_auth = access.check_auth
    _check_library_auth = access.check_library_auth

    cmd_start = basics.cmd_start
    cmd_lang = preferences.cmd_lang
    cmd_undo = undo.cmd_undo
    cmd_status = status.cmd_status
    cmd_history = history.cmd_history
    cmd_stats = stats.cmd_stats
    cmd_cancel = cancel.cmd_cancel
    cmd_check = check.cmd_check
    _handle_cancel_all = cancel.handle_cancel_all
    _handle_history_undo = undo.handle_history_undo

    handle_text = intake.handle_text
    cmd_get = intake.cmd_get
    _handle_card_action = card_callbacks.handle_card_action
    _deliver_copy = handoff.deliver_copy
    _send_saved_file = handoff.send_saved_file

    cmd_sweep = sweep_command.cmd_sweep
    _handle_sweep_decision = sweep_callbacks.handle_sweep_decision
    _handle_sweep_reason = sweep_callbacks.handle_sweep_reason


def create_bot(config: Config) -> Application:
    """Create and configure the Telegram bot application."""
    bot = MusicBot(config)

    async def _post_init(application: Application) -> None:
        application.bot_data["music_bot"] = bot
        bot.attach(application.bot)
        await basics.register_bot_commands(application)
        bot.runner.start()
        for batch in bot.queue_store.active_batches():
            bot.cards.request(batch.id)
        sweep_lifecycle.start_library_sweep(bot, application)

    async def _post_shutdown(application: Application) -> None:
        await bot.runner.stop()
        await sweep_lifecycle.stop_library_sweep(application)

    # Default media_write_timeout is 20s; large lossless uploads routinely exceed that.
    builder = (
        Application.builder()
        .token(config.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .connect_timeout(30)
        .read_timeout(120)
        .write_timeout(120)
        .media_write_timeout(600)
        .pool_timeout(30)
        .concurrent_updates(True)
    )
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
    app.add_handler(CommandHandler(["lang", "language"], bot.cmd_lang))
    app.add_handler(CommandHandler(["get", "import"], bot.cmd_get))
    app.add_handler(CommandHandler("undo", bot.cmd_undo))
    app.add_handler(CommandHandler("status", bot.cmd_status))
    app.add_handler(CommandHandler("history", bot.cmd_history))
    app.add_handler(CommandHandler("stats", bot.cmd_stats))
    app.add_handler(CommandHandler("check", bot.cmd_check))
    app.add_handler(CommandHandler("sweep", bot.cmd_sweep))
    app.add_handler(CommandHandler("cancel", bot.cmd_cancel))
    app.add_handler(CallbackQueryHandler(bot.handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text))
    app.add_error_handler(_on_error)

    logger.info("Telegram bot configured (local_api=%s)", bool(config.telegram_api_base_url))
    return app


async def _on_error(update: object, context) -> None:
    """Log unhandled exceptions from conversation handlers."""
    logger.error("Unhandled Telegram error: %s", context.error, exc_info=context.error)
