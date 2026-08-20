"""Comprehensive tests for bot handlers - MusicBot class and helper functions."""

from __future__ import annotations

import asyncio
import os

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from music_downloader.catalog.track import TrackInfo
from music_downloader.playlist_import.job import JobStatus
from music_downloader.soulseek.query import clean_search_title as _clean_search_title
from music_downloader.soulseek.query import extract_latin_keywords as _extract_latin_keywords
from music_downloader.soulseek.query import has_non_latin_script as _has_non_latin_script
from music_downloader.soulseek.result import SearchResult
from music_downloader.telegram.app import MusicBot
from music_downloader.telegram.messages import code_span, md_code_safe, progress_bar
from music_downloader.telegram.messages import escape_md as _escape_md
from music_downloader.telegram.messages import safe_edit as _safe_edit
from music_downloader.telegram.session import PendingDownload, PendingSearch


def _make_config():
    """Create a mock Config object with isolated DB per instance."""
    td = tempfile.mkdtemp()
    config = MagicMock()
    config.telegram_bot_token = "test-token"
    config.spotify_client_id = "test-id"
    config.spotify_client_secret = "test-secret"
    config.slskd_host = "http://localhost:5030"
    config.slskd_api_key = "test-key"
    config.telegram_allowed_users = {12345}
    config.auto_mode = False
    config.max_results = 5
    config.duration_tolerance_secs = 5
    config.exclude_keywords = ["live", "remix"]
    config.download_dir = os.path.join(td, "downloads")
    config.output_dir = os.path.join(td, "music")
    config.data_dir = os.path.join(td, "data")
    config.filename_template = "{artist} - {title}"
    config.search_timeout_secs = 30
    config.download_timeout_secs = 600
    config.telegram_library_users = set()
    return config


def _make_track():
    return TrackInfo(
        artist="Nancy Sinatra",
        title="Bang Bang",
        album="How Does That Grab You?",
        duration_ms=162_000,
        spotify_url="https://open.spotify.com/track/xxx",
        year="1966",
    )


def _make_search_result(idx=0):
    return SearchResult(
        username=f"user{idx}",
        filename=f"\\Music\\Nancy Sinatra - Bang Bang {idx}.flac",
        size=30_000_000,
        bit_rate=900,
        bit_depth=16,
        sample_rate=44100,
        length=162,
        has_free_slot=True,
        upload_speed=1_000_000,
        queue_length=0,
    )


def _make_update(user_id=12345, chat_id=67890, text="Nancy Sinatra Bang Bang"):
    """Create a mock Telegram Update object."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.message = AsyncMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_callback_update(user_id=12345, chat_id=67890, data="dl:0"):
    """Create a mock callback query Update."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.callback_query = AsyncMock()
    update.callback_query.from_user.id = user_id
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.edit_message_caption = AsyncMock()
    return update


def _make_context(chat_id=67890):
    """Create a mock context."""
    context = MagicMock()
    context.bot = AsyncMock()
    context.bot.send_message = AsyncMock()
    context.bot.send_audio = AsyncMock()
    context.bot.send_document = AsyncMock()
    context.bot.edit_message_reply_markup = AsyncMock()
    context.bot.edit_message_caption = AsyncMock()
    context.bot.edit_message_text = AsyncMock()
    context.application = MagicMock()
    context.application.create_task = MagicMock(side_effect=lambda coro, **kw: asyncio.ensure_future(coro))
    return context


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestEscapeMd:
    def test_escapes_v1_special_chars(self):
        assert _escape_md("hello_world") == "hello\\_world"
        assert _escape_md("*bold*") == "\\*bold\\*"
        assert _escape_md("[link](url)") == "\\[link](url)"
        assert _escape_md("`code`") == "\\`code\\`"

    def test_v1_ignores_other_chars(self):
        """V1 renders backslashes before non-special chars literally — don't add them."""
        assert _escape_md("Artist - Title (Remix)!") == "Artist - Title (Remix)!"
        assert _escape_md("A.B-C+D") == "A.B-C+D"

    def test_plain_text_unchanged(self):
        assert _escape_md("hello world") == "hello world"

    def test_empty_string(self):
        assert _escape_md("") == ""


class TestCodeSpan:
    def test_wraps_in_backticks(self):
        assert code_span("file.flac") == "`file.flac`"

    def test_neutralizes_inner_backticks(self):
        span = code_span("evil`name.flac")
        assert span.startswith("`") and span.endswith("`")
        assert "`" not in span[1:-1]

    def test_md_code_safe_replaces_backticks(self):
        assert "`" not in md_code_safe("a`b`c")
        assert md_code_safe("clean.flac") == "clean.flac"


class TestProgressBar:
    def test_zero_percent(self):
        assert progress_bar(0) == "▱" * 10

    def test_full(self):
        assert progress_bar(100) == "▰" * 10

    def test_half(self):
        assert progress_bar(50) == "▰" * 5 + "▱" * 5

    def test_clamps_out_of_range(self):
        assert progress_bar(-5) == "▱" * 10
        assert progress_bar(150) == "▰" * 10

    def test_custom_width(self):
        assert progress_bar(50, width=4) == "▰▰▱▱"


class TestSafeEdit:
    @pytest.mark.asyncio
    async def test_success(self):
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        result = await _safe_edit(msg, "new text")
        assert result is True
        msg.edit_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_bad_request(self):
        from telegram.error import BadRequest

        msg = AsyncMock()
        msg.edit_text = AsyncMock(side_effect=BadRequest("Message not modified"))
        result = await _safe_edit(msg, "text")
        assert result is False

    @pytest.mark.asyncio
    async def test_timed_out(self):
        from telegram.error import TimedOut

        msg = AsyncMock()
        msg.edit_text = AsyncMock(side_effect=TimedOut())
        result = await _safe_edit(msg, "text")
        assert result is False

    @pytest.mark.asyncio
    async def test_network_error(self):
        from telegram.error import NetworkError

        msg = AsyncMock()
        msg.edit_text = AsyncMock(side_effect=NetworkError("connection failed"))
        result = await _safe_edit(msg, "text")
        assert result is False


class TestHasNonLatinScript:
    def test_latin_only(self):
        assert _has_non_latin_script("Hello World") is False

    def test_cjk(self):
        assert _has_non_latin_script("紅") is True

    def test_cyrillic(self):
        assert _has_non_latin_script("Привет") is True

    def test_mixed(self):
        assert _has_non_latin_script("紅 - KURENAI") is True

    def test_empty(self):
        assert _has_non_latin_script("") is False

    def test_numbers_only(self):
        assert _has_non_latin_script("12345") is False


class TestExtractLatinKeywords:
    def test_mixed_script(self):
        result = _extract_latin_keywords("紅 - KURENAI - Single Long Version")
        assert "KURENAI" in result
        # Noise words should be filtered
        assert "Single" not in result
        assert "Long" not in result
        assert "Version" not in result

    def test_all_noise(self):
        result = _extract_latin_keywords("The Single Version Mix")
        assert result == []

    def test_pure_latin(self):
        result = _extract_latin_keywords("Purple Rain")
        assert "Purple" in result
        assert "Rain" in result

    def test_short_words_filtered(self):
        result = _extract_latin_keywords("I Am A Star")
        # Single-char words filtered by {2,} regex
        assert "Star" in result


class TestCleanSearchTitleExtended:
    def test_deluxe_edition(self):
        assert _clean_search_title("Song - Deluxe Edition") == "Song"

    def test_anniversary_edition(self):
        assert _clean_search_title("Song - Anniversary Edition") == "Song"

    def test_super_deluxe(self):
        assert _clean_search_title("Song - Super Deluxe") == "Song"

    def test_paren_mono(self):
        assert _clean_search_title("Song (Mono)") == "Song"

    def test_paren_stereo(self):
        assert _clean_search_title("Song (Stereo)") == "Song"

    def test_year_mix(self):
        assert _clean_search_title("Song (2009 Mix)") == "Song"


# ---------------------------------------------------------------------------
# MusicBot tests
# ---------------------------------------------------------------------------


class TestMusicBotInit:
    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_init(self, mock_slskd, mock_spotify):
        config = _make_config()
        bot = MusicBot(config)
        assert bot.auto_mode is False
        assert bot.pending == {}
        assert bot.downloads == {}
        assert bot.history_repo is not None


class TestMusicBotAuthorization:
    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_is_authorized_empty_denies_all(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.telegram_allowed_users = set()
        bot = MusicBot(config)
        assert bot._is_authorized(99999) is False

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_is_authorized_allowed(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.telegram_allowed_users = {12345, 67890}
        bot = MusicBot(config)
        assert bot._is_authorized(12345) is True
        assert bot._is_authorized(99999) is False

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_check_auth_denied(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.telegram_allowed_users = {11111}
        bot = MusicBot(config)
        update = _make_update(user_id=99999)
        result = await bot._check_auth(update)
        assert result is False
        update.message.reply_text.assert_called_once_with("You are not authorized to use this bot.")

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_check_auth_allowed(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.telegram_allowed_users = {12345}
        bot = MusicBot(config)
        update = _make_update()
        result = await bot._check_auth(update)
        assert result is True


class TestMusicBotCancellation:
    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cancel_chat_operations_empty(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        had_work = await bot._cancel_chat_operations(12345)
        assert had_work is False

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cancel_chat_operations_with_pending(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.pending[12345] = PendingSearch(query="test")
        had_work = await bot._cancel_chat_operations(12345)
        assert had_work is True
        assert 12345 not in bot.pending

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cancel_removes_downloads_for_chat(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.downloads["1"] = PendingDownload(
            track=_make_track(),
            result=_make_search_result(),
            chat_id=12345,
        )
        bot.downloads["2"] = PendingDownload(
            track=_make_track(),
            result=_make_search_result(),
            chat_id=99999,
        )
        await bot._cancel_chat_operations(12345)
        assert "1" not in bot.downloads
        assert "2" in bot.downloads

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_is_stale(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._chat_generation[123] = 5
        assert bot._is_stale(123, 5) is False
        assert bot._is_stale(123, 4) is True
        assert bot._is_stale(123, 6) is True

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_track_task(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        loop = asyncio.new_event_loop()
        task = loop.create_future()
        task.set_result(None)
        bot._track_task(123, task)
        assert task in bot._active_tasks.get(123, set())
        loop.close()


class TestMusicBotCommands:
    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_start(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_update()
        context = _make_context()
        await bot.cmd_start(update, context)
        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args
        assert "Send me a song name" in call_args[0][0]
        assert "/import" in call_args[0][0]
        assert "/cancel" in call_args[0][0]
        assert "/lang" in call_args[0][0]

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_start_unauthorized(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.telegram_allowed_users = {11111}
        bot = MusicBot(config)
        update = _make_update(user_id=99999)
        context = _make_context()
        await bot.cmd_start(update, context)
        update.message.reply_text.assert_called_once_with("You are not authorized to use this bot.")

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_help(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_update()
        context = _make_context()
        await bot.cmd_help(update, context)
        update.message.reply_text.assert_called()

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_auto(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_update()
        context = _make_context()
        await bot.cmd_auto(update, context)
        call_args = update.message.reply_text.call_args
        assert "OFF" in call_args[0][0]

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_auto_on(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.auto_mode = True
        bot = MusicBot(config)
        update = _make_update()
        context = _make_context()
        await bot.cmd_auto(update, context)
        call_args = update.message.reply_text.call_args
        assert "ON" in call_args[0][0]

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_status_empty(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_update()
        context = _make_context()
        await bot.cmd_status(update, context)
        update.message.reply_text.assert_called_once_with("No active searches, downloads, or imports.")

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_status_with_pending(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.pending[67890] = PendingSearch(query="test", track=_make_track())
        update = _make_update()
        context = _make_context()
        await bot.cmd_status(update, context)
        call_args = update.message.reply_text.call_args
        assert "Nancy Sinatra" in call_args[0][0]

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_status_pending_without_track(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.pending[67890] = PendingSearch(query="artist_with*md", track=None)
        update = _make_update()
        context = _make_context()
        await bot.cmd_status(update, context)
        call_args = update.message.reply_text.call_args
        assert "artist_with*md" in call_args[0][0]

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_status_ignores_other_chats(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.pending[11111] = PendingSearch(query="secret", track=_make_track())
        update = _make_update()
        context = _make_context()
        await bot.cmd_status(update, context)
        update.message.reply_text.assert_called_once_with("No active searches, downloads, or imports.")

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_status_with_downloads(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.downloads["1"] = PendingDownload(
            track=_make_track(),
            result=_make_search_result(),
            chat_id=67890,
        )
        update = _make_update()
        context = _make_context()
        await bot.cmd_status(update, context)
        call_args = update.message.reply_text.call_args
        assert "Active downloads" in call_args[0][0]

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_history_empty(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_update()
        context = _make_context()
        await bot.cmd_history(update, context)
        update.message.reply_text.assert_called_once_with("No downloads yet.")

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_history_with_entries(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        # Add entries via the DB-backed history repo
        bot.history_repo.add(
            artist="Artist",
            title="Song",
            filename="Artist - Song.flac",
            source_user="user1",
            status="success",
            chat_id=67890,
        )
        bot.history_repo.add(
            artist="Artist",
            title="Song2",
            filename="Artist - Song2.flac",
            source_user="user1",
            status="rejected",
            chat_id=67890,
        )
        bot.history_repo.add(
            artist="Artist",
            title="Song3",
            filename="Artist - Song3.flac",
            source_user="user1",
            status="failed",
            chat_id=67890,
        )
        update = _make_update()
        context = _make_context()
        await bot.cmd_history(update, context)
        call_args = update.message.reply_text.call_args
        text = call_args[0][0]
        assert "Recent downloads" in text


class TestMusicBotCallbackHandler:
    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_auto_toggle_on(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_callback_update(data="auto:on")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert bot.is_auto(update.effective_chat.id) is True
        # Per-chat toggle: config default and other chats are untouched.
        assert bot.auto_mode is False
        assert bot.is_auto(99999) is False

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_auto_toggle_off(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.auto_mode = True
        bot = MusicBot(config)
        update = _make_callback_update(data="auto:off")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert bot.is_auto(update.effective_chat.id) is False
        # Other chats still follow the config default.
        assert bot.is_auto(99999) is True

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_duplicate_cancel(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.pending[67890] = PendingSearch(query="test")
        update = _make_callback_update(data="dup:cancel")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert 67890 not in bot.pending

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_duplicate_continue(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.pending[67890] = PendingSearch(query="test song")
        update = _make_callback_update(data="dup:continue")
        context = _make_context()
        # Mock _do_search to prevent actual execution
        bot._do_search = AsyncMock()
        await bot.handle_callback(update, context)
        bot._do_search.assert_called_once()

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_spotify_cancel(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._spotify_candidates[67890] = [_make_track()]
        update = _make_callback_update(data="sp:cancel")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert 67890 not in bot._spotify_candidates

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_spotify_select(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._spotify_candidates[67890] = [_make_track(), _make_track()]
        update = _make_callback_update(data="sp:0")
        context = _make_context()
        bot._do_slskd_search = AsyncMock()
        await bot.handle_callback(update, context)
        bot._do_slskd_search.assert_called_once()

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_spotify_select_invalid_index(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._spotify_candidates[67890] = [_make_track()]
        update = _make_callback_update(data="sp:99")
        context = _make_context()
        await bot.handle_callback(update, context)

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_spotify_page(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._spotify_candidates[67890] = [_make_track() for _ in range(12)]
        bot._spotify_page[67890] = 0
        update = _make_callback_update(data="sp_page:1")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert bot._spotify_page[67890] == 1

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_spotify_page_expired(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_callback_update(data="sp_page:0")
        context = _make_context()
        await bot.handle_callback(update, context)
        update.callback_query.edit_message_text.assert_called_with("Search expired. Send a new query.")

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_spotify_page_invalid(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._spotify_candidates[67890] = [_make_track()]
        update = _make_callback_update(data="sp_page:abc")
        context = _make_context()
        # Should not raise
        await bot.handle_callback(update, context)

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_download_cancel(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.pending[67890] = PendingSearch(query="test", track=_make_track(), results=[_make_search_result()])
        update = _make_callback_update(data="dl:cancel")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert 67890 not in bot.pending

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_download_select(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        track = _make_track()
        result = _make_search_result()
        bot.pending[67890] = PendingSearch(query="test", track=track, results=[result])
        update = _make_callback_update(data="dl:0")
        context = _make_context()
        # Mock the download to prevent actual execution
        bot._do_download = AsyncMock()
        context.application.create_task = MagicMock(return_value=MagicMock())
        await bot.handle_callback(update, context)
        context.application.create_task.assert_called_once()
        update.callback_query.edit_message_reply_markup.assert_awaited()

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_download_auto_pick(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        track = _make_track()
        result = _make_search_result()
        bot.pending[67890] = PendingSearch(query="test", track=track, results=[result])
        update = _make_callback_update(data="dl:auto")
        context = _make_context()
        bot._do_download = AsyncMock()
        context.application.create_task = MagicMock(return_value=MagicMock())
        await bot.handle_callback(update, context)
        context.application.create_task.assert_called_once()

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_download_select_expired(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_callback_update(data="dl:0")
        context = _make_context()
        await bot.handle_callback(update, context)
        update.callback_query.edit_message_text.assert_called_with("Search expired. Send a new query.")

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_download_select_invalid_index(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.pending[67890] = PendingSearch(query="test", track=_make_track(), results=[_make_search_result()])
        update = _make_callback_update(data="dl:99")
        context = _make_context()
        await bot.handle_callback(update, context)

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_results_page(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        track = _make_track()
        results = [_make_search_result(i) for i in range(15)]
        bot.pending[67890] = PendingSearch(query="test", track=track, results=results)
        update = _make_callback_update(data="dl_page:1")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert bot.pending[67890].page == 1

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_results_page_expired(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_callback_update(data="dl_page:0")
        context = _make_context()
        await bot.handle_callback(update, context)
        update.callback_query.edit_message_text.assert_called_with("Search expired. Send a new query.")

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_approve_download(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.processor = MagicMock()
        bot.processor.process_file = MagicMock(return_value="/music/Artist - Song.flac")
        bot._embed_spotify_artwork = AsyncMock()
        bot._dismiss_other_downloads = AsyncMock()
        track = _make_track()
        result = _make_search_result()
        bot.downloads["1"] = PendingDownload(
            track=track,
            result=result,
            chat_id=67890,
            source_path="/downloads/song.flac",
        )
        update = _make_callback_update(data="approve:1")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert "1" not in bot.downloads
        assert bot.history_repo.count() == 1

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_approve_process_fails(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.processor = MagicMock()
        bot.processor.process_file = MagicMock(return_value=None)
        track = _make_track()
        result = _make_search_result()
        bot.downloads["1"] = PendingDownload(
            track=track,
            result=result,
            chat_id=67890,
            source_path="/downloads/song.flac",
        )
        update = _make_callback_update(data="approve:1")
        context = _make_context()
        await bot.handle_callback(update, context)

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_approve_no_source_path(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        track = _make_track()
        result = _make_search_result()
        bot.downloads["1"] = PendingDownload(
            track=track,
            result=result,
            chat_id=67890,
            source_path=None,
        )
        update = _make_callback_update(data="approve:1")
        context = _make_context()
        await bot.handle_callback(update, context)

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_reject_download(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        track = _make_track()
        result = _make_search_result()
        bot.downloads["1"] = PendingDownload(
            track=track,
            result=result,
            chat_id=67890,
        )
        update = _make_callback_update(data="reject:1")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert "1" not in bot.downloads
        assert bot.history_repo.count() == 1
        records = bot.history_repo.get_recent(1)
        assert records[0].status == "rejected"

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_approve_expired(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_callback_update(data="approve:999")
        context = _make_context()
        await bot.handle_callback(update, context)

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_unauthorized_callback(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.telegram_allowed_users = {11111}
        bot = MusicBot(config)
        update = _make_callback_update(user_id=99999, data="auto:on")
        context = _make_context()
        await bot.handle_callback(update, context)
        # Should not change auto mode for the chat
        assert bot.is_auto(update.effective_chat.id) is False


class TestMusicBotHelpers:
    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_format_results(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        track = _make_track()
        results = [_make_search_result(i) for i in range(3)]
        text = bot._format_results(track, results)
        assert "Nancy Sinatra" in text
        assert "Bang Bang" in text
        assert "#1" in text
        assert "#3" in text

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_format_results_fallback(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        track = _make_track()
        results = [_make_search_result()]
        text = bot._format_results(track, results, is_fallback=True)
        assert "No FLAC found" in text

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_format_results_pagination(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        track = _make_track()
        results = [_make_search_result(i) for i in range(15)]
        text = bot._format_results(track, results, page=0, page_size=5)
        assert "Page 1/" in text

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_format_spotify_results(self, mock_slskd, mock_spotify):
        tracks = [_make_track() for _ in range(3)]
        text = MusicBot._format_spotify_results(tracks)
        assert "Multiple matches" in text
        assert "Nancy Sinatra" in text

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_format_spotify_results_escapes_markdown(self, mock_slskd, mock_spotify):
        tracks = [
            TrackInfo(
                artist="AC_DC",
                title="Hells*Bells",
                album="Back[in]Black",
                duration_ms=312_000,
                spotify_url="https://open.spotify.com/track/xxx",
                year="1980",
            )
        ]
        text = MusicBot._format_spotify_results(tracks)
        assert "AC\\_DC" in text
        assert "Hells\\*Bells" in text
        # ']' is not special in Markdown V1; only '[' needs the escape.
        assert "Back\\[in]Black" in text

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_format_spotify_results_pagination(self, mock_slskd, mock_spotify):
        tracks = [_make_track() for _ in range(12)]
        text = MusicBot._format_spotify_results(tracks, page=0, page_size=5)
        assert "page 1/" in text

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_add_history(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        track = _make_track()
        result = _make_search_result()
        await bot._add_history(track, result, "success")
        assert bot.history_repo.count() == 1
        records = bot.history_repo.get_recent(1)
        assert records[0].status == "success"

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_add_history_persists_multiple(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        track = _make_track()
        result = _make_search_result()
        for _ in range(55):
            await bot._add_history(track, result, "success")
        assert bot.history_repo.count() == 55

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_next_dl_id(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        id1 = bot._next_dl_id()
        id2 = bot._next_dl_id()
        assert id1 != id2
        assert id1 == "1"
        assert id2 == "2"


class TestMusicBotHandleText:
    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_empty_text_ignored(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_update(text="   ")
        context = _make_context()
        await bot.handle_text(update, context)
        # Should not proceed to search

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_similar_files_found(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.processor = MagicMock()
        bot.processor.find_similar = MagicMock(return_value=["Artist - Song.flac"])
        update = _make_update(text="Artist Song")
        context = _make_context()
        await bot.handle_text(update, context)
        # Should show duplicate warning
        update.message.reply_text.assert_called_once()
        call_text = update.message.reply_text.call_args[0][0]
        assert "Similar files" in call_text

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_unauthorized_text(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.telegram_allowed_users = {11111}
        bot = MusicBot(config)
        update = _make_update(user_id=99999, text="test")
        context = _make_context()
        await bot.handle_text(update, context)
        update.message.reply_text.assert_called_once_with("You are not authorized to use this bot.")


class TestMusicBotDoSearch:
    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_no_spotify_results(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.spotify = MagicMock()
        bot.spotify.search_multiple = MagicMock(return_value=[])
        update = _make_update()
        context = _make_context()
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        context.bot.send_message = AsyncMock(return_value=msg)
        bot._chat_generation[67890] = 0
        await bot._do_search(update, context, "nonexistent song", 0)

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_single_spotify_result(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.spotify = MagicMock()
        bot.spotify.search_multiple = MagicMock(return_value=[_make_track()])
        bot._do_slskd_search = AsyncMock()
        update = _make_update()
        context = _make_context()
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        context.bot.send_message = AsyncMock(return_value=msg)
        bot._chat_generation[67890] = 0
        await bot._do_search(update, context, "Nancy Sinatra Bang Bang", 0)
        bot._do_slskd_search.assert_called_once()

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_multiple_spotify_results(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        tracks = [_make_track(), _make_track()]
        tracks[1].album = "Different Album"
        bot.spotify = MagicMock()
        bot.spotify.search_multiple = MagicMock(return_value=tracks)
        update = _make_update()
        context = _make_context()
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        context.bot.send_message = AsyncMock(return_value=msg)
        bot._chat_generation[67890] = 0
        await bot._do_search(update, context, "Nancy Sinatra Bang Bang", 0)
        assert 67890 in bot._spotify_candidates

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_stale_search_aborted(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.spotify = MagicMock()
        bot.spotify.search_multiple = MagicMock(return_value=[_make_track()])
        bot._do_slskd_search = AsyncMock()
        update = _make_update()
        context = _make_context()
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        context.bot.send_message = AsyncMock(return_value=msg)
        bot._chat_generation[67890] = 5  # Set generation ahead
        await bot._do_search(update, context, "test", 0)  # generation 0 is stale
        bot._do_slskd_search.assert_not_called()

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_exception_handled(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.spotify = MagicMock()
        bot.spotify.search_multiple = MagicMock(side_effect=Exception("API error"))
        update = _make_update()
        context = _make_context()
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        context.bot.send_message = AsyncMock(return_value=msg)
        bot._chat_generation[67890] = 0
        await bot._do_search(update, context, "test", 0)
        # Should not raise

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_artist_filter(self, mock_slskd, mock_spotify):
        """When query has 'Artist - Title', filter by artist."""
        bot = MusicBot(_make_config())
        t1 = _make_track()
        t2 = TrackInfo(
            artist="Other Artist", title="Bang Bang", album="X", duration_ms=162000, spotify_url="", year="2024"
        )
        bot.spotify = MagicMock()
        bot.spotify.search_multiple = MagicMock(return_value=[t1, t2])
        bot._do_slskd_search = AsyncMock()
        update = _make_update()
        context = _make_context()
        msg = AsyncMock()
        msg.edit_text = AsyncMock()
        context.bot.send_message = AsyncMock(return_value=msg)
        bot._chat_generation[67890] = 0
        await bot._do_search(update, context, "Nancy Sinatra - Bang Bang", 0)
        # Should filter to only Nancy Sinatra -> single result -> auto slskd search
        bot._do_slskd_search.assert_called_once()


class TestMusicBotDismissOtherDownloads:
    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_dismiss(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.pending[67890] = PendingSearch(query="test", track=_make_track(), message_id=100)
        bot.downloads["2"] = PendingDownload(
            track=_make_track(),
            result=_make_search_result(),
            chat_id=67890,
            approval_message_id=200,
        )
        context = _make_context()
        await bot._dismiss_other_downloads(context, 67890)
        assert 67890 not in bot.pending
        assert "2" not in bot.downloads


class TestMusicBotEditApprovalMessage:
    @pytest.mark.asyncio
    async def test_edit_caption(self):
        query = AsyncMock()
        query.edit_message_caption = AsyncMock()
        await MusicBot._edit_approval_message(query, "test")
        query.edit_message_caption.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_to_text(self):
        query = AsyncMock()
        query.edit_message_caption = AsyncMock(side_effect=Exception("no caption"))
        query.edit_message_text = AsyncMock()
        await MusicBot._edit_approval_message(query, "test")
        query.edit_message_text.assert_called_once()


# ---------------------------------------------------------------------------
# IDOR protection tests
# ---------------------------------------------------------------------------


class TestIDORProtection:
    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_approval_idor_blocked(self, mock_slskd, mock_spotify):
        """Approval from a different chat_id should be silently rejected."""
        bot = MusicBot(_make_config())
        track = _make_track()
        result = _make_search_result()
        bot.downloads["1"] = PendingDownload(track=track, result=result, chat_id=111, source_path="/tmp/f.flac")
        update = _make_callback_update(chat_id=999, data="approve:1")
        context = _make_context()
        await bot.handle_callback(update, context)
        # Download should still be in the dict (not popped by wrong chat)
        assert "1" in bot.downloads

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_retry_idor_blocked(self, mock_slskd, mock_spotify):
        """Retry from a different chat_id should be silently rejected."""
        bot = MusicBot(_make_config())
        track = _make_track()
        result = _make_search_result()
        bot.downloads["1"] = PendingDownload(track=track, result=result, chat_id=111)
        update = _make_callback_update(chat_id=999, data="retry:1")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert "1" in bot.downloads

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_next_result_idor_blocked(self, mock_slskd, mock_spotify):
        """Next-result from a different chat should be silently rejected."""
        bot = MusicBot(_make_config())
        track = _make_track()
        result = _make_search_result()
        bot.downloads["1"] = PendingDownload(track=track, result=result, chat_id=111, result_index=0)
        bot.pending[999] = PendingSearch(query="test", track=track, results=[result, _make_search_result(1)])
        update = _make_callback_update(chat_id=999, data="next:1")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert "1" in bot.downloads


# ---------------------------------------------------------------------------
# Retry result_index tests
# ---------------------------------------------------------------------------


class TestRetryResultIndex:
    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_retry_preserves_result_index(self, mock_slskd, mock_spotify):
        """Retry should pass the stored result_index, not hardcoded 0."""
        bot = MusicBot(_make_config())
        track = _make_track()
        result = _make_search_result(3)
        bot.downloads["5"] = PendingDownload(track=track, result=result, chat_id=67890, result_index=3)
        update = _make_callback_update(chat_id=67890, data="retry:5")
        context = _make_context()

        with patch.object(bot, "_do_download", new_callable=AsyncMock) as mock_dl:
            await bot.handle_callback(update, context)
            mock_dl.assert_called_once()
            # result_index is the last positional arg
            assert mock_dl.call_args[0][-1] == 3

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_retry_pops_old_entry(self, mock_slskd, mock_spotify):
        """Retry should remove the old download entry to prevent leaks."""
        bot = MusicBot(_make_config())
        track = _make_track()
        result = _make_search_result()
        bot.downloads["1"] = PendingDownload(track=track, result=result, chat_id=67890)
        update = _make_callback_update(chat_id=67890, data="retry:1")
        context = _make_context()

        with patch.object(bot, "_do_download", new_callable=AsyncMock):
            await bot.handle_callback(update, context)
            assert "1" not in bot.downloads

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_next_result_uses_stored_index(self, mock_slskd, mock_spotify):
        """Next-result should use stored result_index + 1."""
        bot = MusicBot(_make_config())
        track = _make_track()
        results = [_make_search_result(i) for i in range(5)]
        bot.pending[67890] = PendingSearch(query="test", track=track, results=results)
        bot.downloads["2"] = PendingDownload(track=track, result=results[2], chat_id=67890, result_index=2)
        update = _make_callback_update(chat_id=67890, data="next:2")
        context = _make_context()

        with patch.object(bot, "_do_download", new_callable=AsyncMock) as mock_dl:
            await bot.handle_callback(update, context)
            mock_dl.assert_called_once()
            # Should download results[3] with index=3
            call_args = mock_dl.call_args[0]
            assert call_args[3] == results[3]  # next_result
            assert call_args[-1] == 3  # next_idx

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_next_result_exhausted(self, mock_slskd, mock_spotify):
        """Next-result on last result should show 'no more results'."""
        bot = MusicBot(_make_config())
        track = _make_track()
        results = [_make_search_result(0)]
        bot.pending[67890] = PendingSearch(query="test", track=track, results=results)
        bot.downloads["1"] = PendingDownload(track=track, result=results[0], chat_id=67890, result_index=0)
        update = _make_callback_update(chat_id=67890, data="next:1")
        context = _make_context()
        await bot.handle_callback(update, context)
        edit_call = update.callback_query.edit_message_text
        assert "No more results" in edit_call.call_args[0][0]


# ---------------------------------------------------------------------------
# _rank_responses tests
# ---------------------------------------------------------------------------


class TestRankResponses:
    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_flac_found(self, mock_slskd, mock_spotify):
        """When FLAC results exist, returns them with is_fallback=False."""
        bot = MusicBot(_make_config())
        track = _make_track()
        flac_result = [_make_search_result()]
        bot.slskd.parse_results = MagicMock(side_effect=[flac_result])
        bot.scorer.score_results = MagicMock(return_value=flac_result)
        ranked, is_fallback = bot._rank_responses([], track)
        assert len(ranked) == 1
        assert is_fallback is False

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_non_flac_fallback(self, mock_slskd, mock_spotify):
        """When only non-FLAC exists, returns with is_fallback=True."""
        bot = MusicBot(_make_config())
        track = _make_track()
        mp3_result = [_make_search_result()]
        # First call (flac_only=True) returns nothing scored, second call returns results
        bot.slskd.parse_results = MagicMock(side_effect=[[], mp3_result])
        bot.scorer.score_results = MagicMock(side_effect=[[], mp3_result])
        ranked, is_fallback = bot._rank_responses([], track)
        assert len(ranked) == 1
        assert is_fallback is True

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_no_results(self, mock_slskd, mock_spotify):
        """When no results match, returns empty list."""
        bot = MusicBot(_make_config())
        track = _make_track()
        bot.slskd.parse_results = MagicMock(return_value=[])
        bot.scorer.score_results = MagicMock(return_value=[])
        ranked, is_fallback = bot._rank_responses([], track)
        assert ranked == []
        assert is_fallback is False

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_max_duration_diff_passed(self, mock_slskd, mock_spotify):
        """max_duration_diff should be forwarded to score_results."""
        bot = MusicBot(_make_config())
        track = _make_track()
        bot.slskd.parse_results = MagicMock(return_value=[_make_search_result()])
        bot.scorer.score_results = MagicMock(return_value=[_make_search_result()])
        bot._rank_responses([], track, max_duration_diff=120)
        call_kwargs = bot.scorer.score_results.call_args[1]
        assert call_kwargs["max_duration_diff"] == 120


# ---------------------------------------------------------------------------
# Import pending separation tests
# ---------------------------------------------------------------------------


class TestImportPendingSeparation:
    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_import_pending_does_not_clobber_regular(self, mock_slskd, mock_spotify):
        """Import flow should use _import_pending, not overwrite self.pending."""
        bot = MusicBot(_make_config())
        track = _make_track()
        results = [_make_search_result()]
        # Simulate active regular search
        bot.pending[67890] = PendingSearch(query="regular", track=track, results=results)
        # Simulate import storing its state
        bot._import_pending[67890] = PendingSearch(query="import", track=track, results=results)
        # Regular search should be untouched
        assert bot.pending[67890].query == "regular"
        assert bot._import_pending[67890].query == "import"

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cancel_clears_import_pending(self, mock_slskd, mock_spotify):
        """Cancellation should clear both pending dicts."""
        bot = MusicBot(_make_config())
        track = _make_track()
        bot.pending[67890] = PendingSearch(query="q", track=track, results=[])
        bot._import_pending[67890] = PendingSearch(query="i", track=track, results=[])
        await bot._cancel_chat_operations(67890)
        assert 67890 not in bot.pending
        assert 67890 not in bot._import_pending


# ---------------------------------------------------------------------------
# Import callback routing tests
# ---------------------------------------------------------------------------


class TestImportCallbackRouting:
    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_import_cancel_prefix(self, mock_slskd, mock_spotify):
        """ix: prefix should cancel the import job."""
        bot = MusicBot(_make_config())
        # Create a real job via the repo
        job_id = bot.import_repo.create_job(67890, "https://spotify.com/playlist/x", "Test", 5)
        update = _make_callback_update(chat_id=67890, data=f"ix:{job_id}")
        context = _make_context()
        await bot.handle_callback(update, context)
        edit_text = update.callback_query.edit_message_text
        assert "cancelled" in edit_text.call_args[0][0].lower()

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_import_idor_wrong_chat(self, mock_slskd, mock_spotify):
        """Import callback from wrong chat should be rejected."""
        bot = MusicBot(_make_config())
        job_id = bot.import_repo.create_job(111, "https://spotify.com/playlist/x", "Test", 5)
        update = _make_callback_update(chat_id=999, data=f"ic:{job_id}")
        context = _make_context()
        await bot.handle_callback(update, context)
        edit_text = update.callback_query.edit_message_text
        assert "not found" in edit_text.call_args[0][0].lower()

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_import_skip_uses_complete_track(self, mock_slskd, mock_spotify):
        """is: prefix should atomically complete the track as skipped."""
        bot = MusicBot(_make_config())
        job_id = bot.import_repo.create_job(67890, "https://spotify.com/playlist/x", "Test", 2)
        bot.import_repo.add_tracks(
            job_id,
            [
                {
                    "position": 1,
                    "artist": "A",
                    "title": "T",
                    "album": "Al",
                    "duration_ms": 1000,
                    "spotify_url": "",
                    "year": "2020",
                },
            ],
        )
        tracks = bot.import_repo.get_tracks_by_job(job_id)
        track_id = tracks[0].id
        bot._active_import[67890] = job_id

        update = _make_callback_update(chat_id=67890, data=f"is:{job_id}:{track_id}")
        context = _make_context()

        with patch.object(bot, "_process_next_import_track", new_callable=AsyncMock):
            await bot.handle_callback(update, context)

        progress = bot.import_repo.get_job_progress(job_id)
        assert progress[2] == 1  # skipped_tracks == 1


class TestPerChatAutoMode:
    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_is_auto_defaults_to_config(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.auto_mode = True
        bot = MusicBot(config)
        assert bot.is_auto(67890) is True
        assert bot.is_auto(11111) is True

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_override_beats_default(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._auto_overrides[67890] = True
        assert bot.is_auto(67890) is True
        assert bot.is_auto(11111) is False

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_auto_reflects_chat_override(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._auto_overrides[67890] = True
        update = _make_update()
        context = _make_context()
        await bot.cmd_auto(update, context)
        assert "ON" in update.message.reply_text.call_args[0][0]


class TestCmdStatusDetails:
    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_status_shows_download_progress(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.downloads["1"] = PendingDownload(
            track=_make_track(),
            result=_make_search_result(),
            chat_id=67890,
            progress_percent=42.0,
        )
        update = _make_update()
        context = _make_context()
        await bot.cmd_status(update, context)
        text = update.message.reply_text.call_args[0][0]
        assert "42%" in text

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_status_shows_awaiting_approval(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.downloads["1"] = PendingDownload(
            track=_make_track(),
            result=_make_search_result(),
            chat_id=67890,
            source_path="/tmp/somefile.flac",
            progress_percent=100.0,
        )
        update = _make_update()
        context = _make_context()
        await bot.cmd_status(update, context)
        text = update.message.reply_text.call_args[0][0]
        assert "awaiting approval" in text

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_status_shows_active_import(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        job_id = bot.import_repo.create_job(67890, "https://spotify.com/playlist/x", "My Playlist", 10)
        bot.import_repo.update_job_status(job_id, JobStatus.active)
        update = _make_update()
        context = _make_context()
        await bot.cmd_status(update, context)
        text = update.message.reply_text.call_args[0][0]
        assert "Active import" in text
        assert "My Playlist" in text
        assert "0/10" in text

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_status_ignores_other_chat_imports(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.import_repo.create_job(11111, "https://spotify.com/playlist/x", "Other", 3)
        update = _make_update()
        context = _make_context()
        await bot.cmd_status(update, context)
        update.message.reply_text.assert_called_once_with("No active searches, downloads, or imports.")


# ---------------------------------------------------------------------------
# _remove_download_file (read-only DOWNLOAD_DIR fallback)
# ---------------------------------------------------------------------------


class TestRemoveDownloadFile:
    def _make_bot_with_download(self):
        config = _make_config()
        with (
            patch("music_downloader.telegram.app.SpotifyResolver"),
            patch("music_downloader.telegram.app.SlskdClient"),
        ):
            bot = MusicBot(config)
        source = os.path.join(config.download_dir, "someuser", "song.flac")
        os.makedirs(os.path.dirname(source))
        with open(source, "w") as f:
            f.write("data")
        return bot, source

    @pytest.mark.asyncio
    async def test_local_delete_skips_slskd(self):
        bot, source = self._make_bot_with_download()
        await bot._remove_download_file(source)
        assert not os.path.exists(source)
        bot.slskd.delete_downloaded_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_none_source_is_noop(self):
        bot, _ = self._make_bot_with_download()
        await bot._remove_download_file(None)
        bot.slskd.delete_downloaded_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_slskd_when_local_delete_fails(self):
        """Read-only DOWNLOAD_DIR: local remove fails, slskd deletes remotely."""
        bot, source = self._make_bot_with_download()
        bot.processor.cleanup_download = MagicMock(return_value=False)

        def _remote_delete(rel_path):
            os.remove(source)
            return True

        bot.slskd.delete_downloaded_file = MagicMock(side_effect=_remote_delete)
        bot.slskd.delete_downloaded_directory = MagicMock(return_value=True)

        await bot._remove_download_file(source)

        bot.slskd.delete_downloaded_file.assert_called_once_with("someuser/song.flac")
        # Parent dir became empty, so the per-user directory is removed remotely too.
        bot.slskd.delete_downloaded_directory.assert_called_once_with("someuser")

    @pytest.mark.asyncio
    async def test_keeps_user_dir_when_not_empty(self):
        bot, source = self._make_bot_with_download()
        sibling = os.path.join(os.path.dirname(source), "other.flac")
        with open(sibling, "w") as f:
            f.write("data")
        bot.processor.cleanup_download = MagicMock(return_value=False)

        def _remote_delete(rel_path):
            os.remove(source)
            return True

        bot.slskd.delete_downloaded_file = MagicMock(side_effect=_remote_delete)
        bot.slskd.delete_downloaded_directory = MagicMock()

        await bot._remove_download_file(source)

        bot.slskd.delete_downloaded_file.assert_called_once_with("someuser/song.flac")
        bot.slskd.delete_downloaded_directory.assert_not_called()

    @pytest.mark.asyncio
    async def test_remote_delete_failure_is_logged_not_raised(self):
        bot, source = self._make_bot_with_download()
        bot.processor.cleanup_download = MagicMock(return_value=False)
        bot.slskd.delete_downloaded_file = MagicMock(return_value=False)
        bot.slskd.delete_downloaded_directory = MagicMock()

        await bot._remove_download_file(source)

        bot.slskd.delete_downloaded_file.assert_called_once()
        bot.slskd.delete_downloaded_directory.assert_not_called()
        assert os.path.exists(source)


# ---------------------------------------------------------------------------
# format_result_reasons
# ---------------------------------------------------------------------------


class TestFormatResultReasons:
    def test_full_reasons_line(self):
        from music_downloader.telegram.messages import format_result_reasons

        track = _make_track()  # 162s reference
        result = _make_search_result()
        result.length = 162
        result.has_free_slot = True
        result.score = 87.4
        line = format_result_reasons(track, result)
        assert "exact duration" in line
        assert "free slot" in line
        assert "87/100" in line

    def test_duration_diff_and_queue(self):
        from music_downloader.telegram.messages import format_result_reasons

        track = _make_track()
        result = _make_search_result()
        result.length = 165
        result.has_free_slot = False
        result.queue_length = 3
        result.score = 60.0
        line = format_result_reasons(track, result)
        assert "±3s" in line
        assert "queue of 3" in line

    def test_no_reference_duration(self):
        from music_downloader.telegram.messages import format_result_reasons

        track = _make_track()
        track.duration_ms = 0
        result = _make_search_result()
        result.score = 0
        result.has_free_slot = False
        result.queue_length = 0
        assert format_result_reasons(track, result) == ""


# ---------------------------------------------------------------------------
# format_search_results
# ---------------------------------------------------------------------------


class TestFormatSearchResults:
    def test_direct_search_fallback_does_not_claim_flac(self):
        """Direct search (no reference duration) must honor is_fallback: an MP3
        fallback list used to be headlined 'Found N FLAC matches'."""
        from music_downloader.telegram.messages import format_search_results

        track = _make_track()
        track.duration_ms = 0  # direct search marker
        result = _make_search_result()
        result.filename = "\\Music\\Nancy Sinatra - Bang Bang.mp3"

        text = format_search_results(track, [result], is_fallback=True)
        assert "FLAC match" not in text
        assert "No FLAC found" in text
        assert "[MP3]" in text

    def test_direct_search_flac_header(self):
        from music_downloader.telegram.messages import format_search_results

        track = _make_track()
        track.duration_ms = 0
        text = format_search_results(track, [_make_search_result()], is_fallback=False)
        assert "Found 1 FLAC match" in text

    def test_spotify_search_fallback_header_unchanged(self):
        from music_downloader.telegram.messages import format_search_results

        track = _make_track()
        result = _make_search_result()
        result.filename = "\\Music\\Nancy Sinatra - Bang Bang.mp3"
        text = format_search_results(track, [result], is_fallback=True)
        assert "No FLAC found" in text
        assert "FLAC match" not in text


# ---------------------------------------------------------------------------
# Pasted link handling
# ---------------------------------------------------------------------------


class TestLinkQueries:
    def _make_bot(self):
        with (
            patch("music_downloader.telegram.app.SpotifyResolver"),
            patch("music_downloader.telegram.app.SlskdClient"),
        ):
            return MusicBot(_make_config())

    @pytest.mark.asyncio
    async def test_spotify_track_link_resolves_directly(self):
        from music_downloader.telegram import search_flow

        bot = self._make_bot()
        bot.spotify.get_track = MagicMock(return_value=_make_track())
        bot._do_slskd_search = AsyncMock()
        update = _make_update(text="https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC")
        context = _make_context()

        handled = await search_flow._handle_link_query(
            bot, update, context, 67890, "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"
        )
        assert handled is True
        bot.spotify.get_track.assert_called_once_with("4uLU6hMCjMI75M1A2tKUQC")
        bot._do_slskd_search.assert_awaited_once()
        assert bot.pending[67890].track is not None

    @pytest.mark.asyncio
    async def test_soundcloud_link_uses_verified_spotify_match(self):
        from music_downloader.catalog.soundcloud import SoundCloudTrack
        from music_downloader.telegram import search_flow

        bot = self._make_bot()
        bot.soundcloud.resolve = MagicMock(return_value=SoundCloudTrack(artist="Forss", title="Flickermood"))
        spotify_match = TrackInfo(
            artist="Forss",
            title="Flickermood",
            album="Soulhack",
            duration_ms=222000,
            spotify_url="https://x",
            year="2003",
        )
        bot.spotify.search_multiple = MagicMock(return_value=[spotify_match])
        bot._do_slskd_search = AsyncMock()
        update = _make_update(text="https://soundcloud.com/forss/flickermood")
        context = _make_context()

        handled = await search_flow._handle_link_query(
            bot, update, context, 67890, "https://soundcloud.com/forss/flickermood"
        )
        assert handled is True
        bot.soundcloud.resolve.assert_called_once_with("https://soundcloud.com/forss/flickermood")
        bot._do_slskd_search.assert_awaited_once()
        assert bot._do_slskd_search.await_args.args[2] is spotify_match

    @pytest.mark.asyncio
    async def test_soundcloud_track_not_on_spotify_searches_directly(self):
        """A wrong same-artist Spotify hit must not replace the SoundCloud track."""
        from music_downloader.catalog.soundcloud import SoundCloudTrack
        from music_downloader.telegram import search_flow

        bot = self._make_bot()
        bot.soundcloud.resolve = MagicMock(return_value=SoundCloudTrack(artist="Ponky", title="Remontada"))
        wrong_track = TrackInfo(
            artist="Ponky",
            title="Barado",
            album="Fire Ritual EP",
            duration_ms=342000,
            spotify_url="https://x",
            year="2024",
        )
        bot.spotify.search_multiple = MagicMock(return_value=[wrong_track])
        bot._do_slskd_search = AsyncMock()
        bot._do_direct_slskd_search = AsyncMock()
        update = _make_update(text="https://soundcloud.com/ponky/remontada")
        context = _make_context()

        handled = await search_flow._handle_link_query(
            bot, update, context, 67890, "https://soundcloud.com/ponky/remontada"
        )
        assert handled is True
        bot._do_slskd_search.assert_not_awaited()
        bot._do_direct_slskd_search.assert_awaited_once()
        assert bot._do_direct_slskd_search.await_args.args[2] == "Ponky Remontada"
        display_track = bot._do_direct_slskd_search.await_args.kwargs["display_track"]
        assert display_track.artist == "Ponky"
        assert display_track.title == "Remontada"

    @pytest.mark.asyncio
    async def test_playlist_link_suggests_import(self):
        from music_downloader.telegram import search_flow

        bot = self._make_bot()
        update = _make_update(text="https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
        context = _make_context()

        handled = await search_flow._handle_link_query(
            bot, update, context, 67890, "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        )
        assert handled is True
        text = update.message.reply_text.call_args.args[0]
        assert "/import" in text

    @pytest.mark.asyncio
    async def test_plain_text_is_not_handled(self):
        from music_downloader.telegram import search_flow

        bot = self._make_bot()
        update = _make_update(text="nancy sinatra bang bang")
        context = _make_context()

        handled = await search_flow._handle_link_query(bot, update, context, 67890, "nancy sinatra bang bang")
        assert handled is False


# ---------------------------------------------------------------------------
# /quality and /undo commands
# ---------------------------------------------------------------------------


class TestQualityCommand:
    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    def test_default_pref_from_config(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.quality_preference = "hires"
        bot = MusicBot(config)
        assert bot.quality_pref(1) == "hires"

    @patch("music_downloader.telegram.app.SpotifyResolver")
    @patch("music_downloader.telegram.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_qp_callback_sets_override(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.quality_preference = "hires"
        bot = MusicBot(config)
        update = _make_callback_update(data="qp:cd")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert bot.quality_pref(update.effective_chat.id) == "cd"
        # Other chats keep the default.
        assert bot.quality_pref(99999) == "hires"


class TestUndoCommand:
    def _make_bot(self):
        with (
            patch("music_downloader.telegram.app.SpotifyResolver"),
            patch("music_downloader.telegram.app.SlskdClient"),
        ):
            return MusicBot(_make_config())

    @pytest.mark.asyncio
    async def test_undo_removes_file_and_marks_history(self):
        bot = self._make_bot()
        target = os.path.join(bot.config.output_dir, "Artist - Song.flac")
        with open(target, "w") as f:
            f.write("data")
        bot.history_repo.add(
            artist="Artist",
            title="Song",
            filename="Artist - Song.flac",
            source_user="u",
            status="success",
            chat_id=67890,
        )
        update = _make_update()
        context = _make_context()
        await bot.cmd_undo(update, context)
        assert not os.path.exists(target)
        assert bot.history_repo.get_last_saved(67890) is None
        text = update.message.reply_text.call_args.args[0]
        assert "Removed from library" in text

    @pytest.mark.asyncio
    async def test_undo_without_saves(self):
        bot = self._make_bot()
        update = _make_update()
        context = _make_context()
        await bot.cmd_undo(update, context)
        text = update.message.reply_text.call_args.args[0]
        assert "Nothing to undo" in text

    @pytest.mark.asyncio
    async def test_undo_falls_back_to_exact_match(self):
        """If the canonical filename is gone (e.g. counter suffix), find_exact locates it."""
        bot = self._make_bot()
        target = os.path.join(bot.config.output_dir, "Artist - Song.mp3")
        with open(target, "w") as f:
            f.write("data")
        bot.history_repo.add(
            artist="Artist",
            title="Song",
            filename="Artist - Song.flac",
            source_user="u",
            status="success",
            chat_id=67890,
        )
        update = _make_update()
        context = _make_context()
        await bot.cmd_undo(update, context)
        assert not os.path.exists(target)
