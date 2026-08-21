"""Locale catalogs, persistence, first-time pick, and /lang."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.ext import ApplicationHandlerStop

from music_downloader.i18n.catalog import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    current_locale,
    gettext,
    negotiate_locale,
    set_locale,
    use_locale,
)
from music_downloader.i18n.store import LocaleStore
from music_downloader.records.database import Database
from music_downloader.telegram.commands.language import FIRST_TIME_PROMPT, build_language_keyboard
from music_downloader.telegram.core.app import MusicBot
from music_downloader.telegram.ui.formatting import welcome_text


@pytest.fixture(autouse=True)
def _reset_locale():
    set_locale("en")
    yield
    set_locale("en")


def _make_config(allowed: set[int] | None = None):
    td = tempfile.mkdtemp()
    config = MagicMock()
    config.telegram_bot_token = "test-token"
    config.spotify_client_id = "test-id"
    config.spotify_client_secret = "test-secret"
    config.slskd_host = "http://localhost:5030"
    config.slskd_api_key = "test-key"
    config.telegram_allowed_users = allowed if allowed is not None else {12345}
    config.auto_mode = False
    config.max_results = 5
    config.duration_tolerance_secs = 5
    config.exclude_keywords = ["live"]
    config.download_dir = os.path.join(td, "downloads")
    config.output_dir = os.path.join(td, "music")
    config.data_dir = os.path.join(td, "data")
    config.filename_template = "{artist} - {title}"
    config.search_timeout_secs = 30
    config.download_timeout_secs = 600
    config.telegram_library_users = set()
    return config


def _make_update(user_id=12345, language_code="en", text="/start"):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.language_code = language_code
    update.effective_chat.id = user_id
    update.callback_query = None
    update.message = AsyncMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.effective_message = update.message
    return update


def _make_lang_callback(user_id=12345, locale="es"):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.language_code = "en"
    update.effective_chat.id = user_id
    query = AsyncMock()
    query.data = f"lang:{locale}"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = AsyncMock()
    update.callback_query = query
    update.message = None
    update.effective_message = query.message
    return update


class TestNegotiateLocale:
    def test_none_defaults_to_english(self):
        assert negotiate_locale(None) == DEFAULT_LOCALE

    def test_exact_and_region(self):
        assert negotiate_locale("es") == "es"
        assert negotiate_locale("es-ES") == "es"
        assert negotiate_locale("de_AT") == "de"
        assert negotiate_locale("gl") == "gl"

    def test_unsupported_falls_back(self):
        assert negotiate_locale("pt-BR") == DEFAULT_LOCALE
        assert negotiate_locale("zh") == DEFAULT_LOCALE


class TestGettext:
    def test_english_is_identity(self):
        with use_locale("en"):
            assert gettext("Cancelled.") == "Cancelled."
            assert gettext("No downloads yet.") == "No downloads yet."

    def test_spanish_translates_known_string(self):
        with use_locale("es"):
            assert gettext("Cancelled.") == "Cancelado."
            assert gettext("No downloads yet.") == "Aún no hay descargas."

    def test_german_and_galician(self):
        with use_locale("de"):
            assert gettext("Cancelled.") == "Abgebrochen."
        with use_locale("gl"):
            assert gettext("Cancelled.") == "Cancelado."

    def test_missing_msgid_falls_back_to_english(self):
        with use_locale("es"):
            assert gettext("definitely-not-a-msgid") == "definitely-not-a-msgid"

    def test_unknown_locale_falls_back_to_english(self):
        assert set_locale("xx") == DEFAULT_LOCALE
        assert gettext("Cancelled.") == "Cancelled."
        set_locale("en")

    def test_welcome_mentions_lang(self):
        with use_locale("en"):
            text = welcome_text()
            assert "/lang" in text
            assert "Send me a song name" in text


class TestLocaleStore:
    def test_get_set_roundtrip(self, tmp_path):
        store = LocaleStore(Database(str(tmp_path / "i18n.db")))
        assert store.get(1) is None
        assert store.set(1, "gl") == "gl"
        assert store.get(1) == "gl"
        assert store.set(1, "de") == "de"
        assert store.get(1) == "de"

    def test_rejects_unknown_locale(self, tmp_path):
        store = LocaleStore(Database(str(tmp_path / "i18n.db")))
        assert store.set(1, "zz") == DEFAULT_LOCALE
        assert store.get(1) == DEFAULT_LOCALE


class TestLanguageKeyboard:
    def test_one_button_per_locale(self):
        kb = build_language_keyboard()
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert labels == list(SUPPORTED_LOCALES.values())
        assert callbacks == [f"lang:{code}" for code in SUPPORTED_LOCALES]


class TestLanguageFlow:
    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_first_use_prompts_and_stops(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_update()
        with pytest.raises(ApplicationHandlerStop):
            await bot.ensure_locale(update, MagicMock())
        update.message.reply_text.assert_awaited()
        assert FIRST_TIME_PROMPT in update.message.reply_text.call_args[0][0]
        assert bot.locale_store.get(12345) is None

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_stored_locale_passes_through(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.locale_store.set(12345, "de")
        update = _make_update()
        await bot.ensure_locale(update, MagicMock())
        update.message.reply_text.assert_not_called()
        assert current_locale() == "de"

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_unauthorized_skips_picker(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config(allowed={111}))
        update = _make_update(user_id=999)
        await bot.ensure_locale(update, MagicMock())
        update.message.reply_text.assert_not_called()
        assert bot.locale_store.get(999) is None

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_lang_callback_persists_and_welcomes(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_lang_callback(locale="es")
        context = MagicMock()
        context.bot.send_message = AsyncMock()
        with pytest.raises(ApplicationHandlerStop):
            await bot.ensure_locale(update, context)
        assert bot.locale_store.get(12345) == "es"
        update.callback_query.edit_message_text.assert_awaited()
        assert "Español" in update.callback_query.edit_message_text.call_args[0][0]
        context.bot.send_message.assert_awaited()
        welcome = context.bot.send_message.call_args.kwargs["text"]
        assert "/import" in welcome
        assert "/lang" in welcome

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_lang_shows_picker(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.locale_store.set(12345, "en")
        update = _make_update()
        await bot.cmd_lang(update, MagicMock())
        update.message.reply_text.assert_awaited()
        assert "language" in update.message.reply_text.call_args[0][0].lower()
