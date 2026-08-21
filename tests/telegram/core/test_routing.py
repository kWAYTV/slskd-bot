"""Callback dispatch: prefixes, toggles, import routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from music_downloader.telegram.core.app import MusicBot
from music_downloader.telegram.core.session import PendingDownload, PendingSearch
from tests.telegram.helpers import (
    _make_callback_update,
    _make_config,
    _make_context,
    _make_search_result,
    _make_track,
)


class TestMusicBotCallbackHandler:
    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
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

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
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

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_spotify_cancel(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._spotify_candidates[67890] = [_make_track()]
        update = _make_callback_update(data="sp:cancel")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert 67890 not in bot._spotify_candidates

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_spotify_select(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._spotify_candidates[67890] = [_make_track(), _make_track()]
        update = _make_callback_update(data="sp:0")
        context = _make_context()
        bot._do_slskd_search = AsyncMock()
        await bot.handle_callback(update, context)
        bot._do_slskd_search.assert_called_once()

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_spotify_select_invalid_index(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._spotify_candidates[67890] = [_make_track()]
        update = _make_callback_update(data="sp:99")
        context = _make_context()
        await bot.handle_callback(update, context)

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_spotify_page(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._spotify_candidates[67890] = [_make_track() for _ in range(12)]
        bot._spotify_page[67890] = 0
        update = _make_callback_update(data="sp_page:1")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert bot._spotify_page[67890] == 1

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_spotify_page_expired(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_callback_update(data="sp_page:0")
        context = _make_context()
        await bot.handle_callback(update, context)
        update.callback_query.edit_message_text.assert_called_with("Search expired. Send a new query.")

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_spotify_page_invalid(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot._spotify_candidates[67890] = [_make_track()]
        update = _make_callback_update(data="sp_page:abc")
        context = _make_context()
        # Should not raise
        await bot.handle_callback(update, context)

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_download_cancel(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.pending[67890] = PendingSearch(query="test", track=_make_track(), results=[_make_search_result()])
        update = _make_callback_update(data="dl:cancel")
        context = _make_context()
        await bot.handle_callback(update, context)
        assert 67890 not in bot.pending

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
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

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
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

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_download_select_expired(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_callback_update(data="dl:0")
        context = _make_context()
        await bot.handle_callback(update, context)
        update.callback_query.edit_message_text.assert_called_with("Search expired. Send a new query.")

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_download_select_invalid_index(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        bot.pending[67890] = PendingSearch(query="test", track=_make_track(), results=[_make_search_result()])
        update = _make_callback_update(data="dl:99")
        context = _make_context()
        await bot.handle_callback(update, context)

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
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

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_results_page_expired(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_callback_update(data="dl_page:0")
        context = _make_context()
        await bot.handle_callback(update, context)
        update.callback_query.edit_message_text.assert_called_with("Search expired. Send a new query.")

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
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

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
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

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
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

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
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

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
    @pytest.mark.asyncio
    async def test_approve_expired(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config())
        update = _make_callback_update(data="approve:999")
        context = _make_context()
        await bot.handle_callback(update, context)

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
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


class TestImportCallbackRouting:
    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
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

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
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

    @patch("music_downloader.telegram.core.app.SpotifyResolver")
    @patch("music_downloader.telegram.core.app.SlskdClient")
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
