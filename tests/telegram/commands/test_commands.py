"""Slash commands: /start /help /quality /status /history /stats /undo."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from slskd_importer.playlist_import.job import JobStatus
from slskd_importer.telegram.core.app import MusicBot
from slskd_importer.telegram.core.session import PendingDownload, PendingSearch
from tests.telegram.helpers import (
    _make_callback_update,
    _make_config,
    _make_context,
    _make_search_result,
    _make_track,
    _make_update,
)


class TestMusicBotCommands:
    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_start(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_update()
        context = _make_context()
        await bot.cmd_start(update, context)
        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args
        assert "Choose your language" in call_args[0][0]
        markup = call_args.kwargs["reply_markup"]
        labels = [btn.text for row in markup.inline_keyboard for btn in row]
        assert labels == ["English", "Español", "Galego", "Deutsch"]

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_start_unauthorized(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.telegram_allowed_users = {11111}
        bot = MusicBot(config)
        update = _make_update(user_id=99999)
        context = _make_context()
        await bot.cmd_start(update, context)
        update.message.reply_text.assert_called_once_with("You are not authorized to use this bot.")

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_start_welcome_after_locale(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._locales[67890] = "en"
        update = _make_update()
        context = _make_context()
        await bot.cmd_start(update, context)
        text = update.message.reply_text.call_args[0][0]
        assert "Send me a song name" in text
        assert "/lang" in text
        assert "/import" in text
        assert "/auto" not in text

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_lang_shows_picker(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._locales[67890] = "en"
        update = _make_update()
        context = _make_context()
        await bot.cmd_lang(update, context)
        text = update.message.reply_text.call_args[0][0]
        assert "Choose your language" in text
        markup = update.message.reply_text.call_args.kwargs["reply_markup"]
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert callbacks == ["lang:en", "lang:es", "lang:gl", "lang:de"]

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_lang_callback_first_pick_shows_welcome(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_callback_update(data="lang:es")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert bot.locale(67890) == "es"
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Envíame el nombre de una canción" in text
        assert bot.prefs_repo.get_locale(67890) == "es"

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_lang_callback_later_confirms(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._locales[67890] = "en"
        update = _make_callback_update(data="lang:de")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert bot.locale(67890) == "de"
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Deutsch" in text

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_stats_empty(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_update()
        context = _make_context()
        await bot.cmd_stats(update, context)
        text = update.message.reply_text.call_args[0][0]
        assert "Download stats" in text
        assert "Total: 0" in text

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_status_empty(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_update()
        context = _make_context()
        await bot.cmd_status(update, context)
        update.message.reply_text.assert_called_once_with("No active searches, downloads, or imports.")

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_status_with_pending(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.pending["1"] = PendingSearch(query="test", track=_make_track(), chat_id=67890, search_id="1")
        update = _make_update()
        context = _make_context()
        await bot.cmd_status(update, context)
        call_args = update.message.reply_text.call_args
        assert "Nancy Sinatra" in call_args[0][0]

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_status_pending_without_track(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.pending["1"] = PendingSearch(query="artist_with*md", track=None, chat_id=67890, search_id="1")
        update = _make_update()
        context = _make_context()
        await bot.cmd_status(update, context)
        call_args = update.message.reply_text.call_args
        assert "artist_with*md" in call_args[0][0]

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_status_ignores_other_chats(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.pending["1"] = PendingSearch(query="secret", track=_make_track(), chat_id=11111, search_id="1")
        update = _make_update()
        context = _make_context()
        await bot.cmd_status(update, context)
        update.message.reply_text.assert_called_once_with("No active searches, downloads, or imports.")

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
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

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_cmd_history_empty(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_update()
        context = _make_context()
        await bot.cmd_history(update, context)
        update.message.reply_text.assert_called_once_with("No downloads yet.")

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
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
        markup = call_args.kwargs["reply_markup"]
        callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert any(cb.startswith("hu:") for cb in callbacks)


class TestCmdStatusDetails:
    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
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

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_status_shows_queued_at_peer(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.downloads["1"] = PendingDownload(
            track=_make_track(),
            result=_make_search_result(),
            chat_id=67890,
            transfer_state="Queued, Remotely",
        )
        update = _make_update()
        context = _make_context()
        await bot.cmd_status(update, context)
        text = update.message.reply_text.call_args[0][0]
        assert "queued at peer" in text

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
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

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
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

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
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


class TestQualityCommand:
    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
    def test_default_pref_from_config(self, mock_slskd, mock_spotify):
        config = _make_config()
        config.quality_preference = "hires"
        bot = MusicBot(config)
        assert bot.quality_pref(1) == "hires"

    @patch("slskd_importer.telegram.core.app.SpotifyResolver")
    @patch("slskd_importer.telegram.core.app.SlskdClient")
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
            patch("slskd_importer.telegram.core.app.SpotifyResolver"),
            patch("slskd_importer.telegram.core.app.SlskdClient"),
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
