"""Library-user ACL and send-then-delete delivery."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from music_downloader.catalog.track import TrackInfo
from music_downloader.soulseek.result import DownloadStatus, SearchResult
from music_downloader.telegram.core.app import MusicBot
from music_downloader.telegram.core.session import PendingDownload, PendingSearch


def _make_config(*, library_users=None):
    td = tempfile.mkdtemp()
    config = MagicMock()
    config.telegram_bot_token = "test-token"
    config.spotify_client_id = "test-id"
    config.spotify_client_secret = "test-secret"
    config.slskd_host = "http://localhost:5030"
    config.slskd_api_key = "test-key"
    config.telegram_allowed_users = {12345, 99999}
    config.telegram_library_users = set() if library_users is None else set(library_users)
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
    return config


def _make_track():
    return TrackInfo(
        artist="Artist",
        title="Title",
        album="Album",
        duration_ms=162000,
        spotify_url="https://open.spotify.com/track/xxx",
        year="2024",
    )


def _make_result():
    return SearchResult(
        username="peer",
        filename="\\Music\\track.flac",
        size=1000,
        bit_depth=16,
        sample_rate=44100,
        length=162,
        has_free_slot=True,
    )


def _make_update(user_id=12345, chat_id=67890, text="/import"):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


@patch("music_downloader.telegram.core.app.SpotifyResolver")
@patch("music_downloader.telegram.core.app.SlskdClient")
class TestCanSaveLibrary:
    def test_empty_list_allows_all(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config(library_users=set()))
        assert bot._can_save_library(12345) is True
        assert bot._can_save_library(None) is True

    def test_restricted_list(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config(library_users={12345}))
        assert bot._can_save_library(12345) is True
        assert bot._can_save_library(99999) is False
        assert bot._can_save_library(None) is False

    @pytest.mark.asyncio
    async def test_import_denied_for_non_library_user(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config(library_users={12345}))
        update = _make_update(user_id=99999)
        result = await bot._check_library_auth(update)
        assert result is False
        update.message.reply_text.assert_awaited()
        assert "library users" in update.message.reply_text.call_args[0][0]


@patch("music_downloader.telegram.core.app.SpotifyResolver")
@patch("music_downloader.telegram.core.app.SlskdClient")
class TestSendThenDelete:
    @pytest.mark.asyncio
    async def test_non_library_user_file_is_deleted(self, mock_slskd, mock_spotify, tmp_path):
        config = _make_config(library_users={12345})
        bot = MusicBot(config)
        source = tmp_path / "track.flac"
        source.write_bytes(b"flac")
        pending = PendingDownload(
            track=_make_track(),
            result=_make_result(),
            chat_id=1,
            source_path=str(source),
            transfer_id="xfer-1",
        )
        bot.downloads["1"] = pending
        bot.slskd.cancel_transfer = MagicMock(return_value=True)
        await bot._cleanup_download_artifacts(pending)
        assert not source.exists()
        bot.slskd.cancel_transfer.assert_called_once_with("peer", "\\Music\\track.flac", "xfer-1")

    @pytest.mark.asyncio
    async def test_do_download_delivers_without_save_keyboard(self, mock_slskd, mock_spotify, tmp_path):
        config = _make_config(library_users={12345})
        bot = MusicBot(config)
        source = tmp_path / "downloads" / "peer" / "track.flac"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"x" * 100)
        bot.processor.find_downloaded_file = MagicMock(return_value=str(source))
        bot.slskd.enqueue_download = MagicMock(return_value=True)
        bot.slskd.wait_for_download = AsyncMock(
            return_value=DownloadStatus(
                username="peer",
                filename="\\Music\\track.flac",
                state="Completed",
                transfer_id="t1",
            )
        )
        bot.slskd.cancel_transfer = MagicMock(return_value=True)
        context = MagicMock()
        context.bot.send_audio = AsyncMock(return_value=MagicMock(message_id=9))
        context.bot.send_document = AsyncMock()
        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        await bot._do_download(context, 1, _make_track(), _make_result(), status_msg, 0, user_id=99999)
        context.bot.send_audio.assert_awaited()
        caption = context.bot.send_audio.call_args.kwargs["caption"]
        assert "not saved" in caption
        assert context.bot.send_audio.call_args.kwargs["reply_markup"] is None
        assert not source.exists()
        records = bot.history_repo.get_recent(1, chat_id=1)
        assert records[0].status == "delivered"

    @pytest.mark.asyncio
    async def test_failed_large_send_not_recorded_as_delivered(self, mock_slskd, mock_spotify, tmp_path):
        """>50MB file where OGG+preview both fail: nothing was sent, so no 'delivered' record."""
        config = _make_config(library_users={12345})
        bot = MusicBot(config)
        source = tmp_path / "downloads" / "peer" / "track.flac"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"x" * 100)
        bot.processor.find_downloaded_file = MagicMock(return_value=str(source))
        bot.slskd.enqueue_download = MagicMock(return_value=True)
        bot.slskd.wait_for_download = AsyncMock(
            return_value=DownloadStatus(
                username="peer",
                filename="\\Music\\track.flac",
                state="Completed",
                transfer_id="t1",
            )
        )
        bot.slskd.cancel_transfer = MagicMock(return_value=True)
        bot._send_large_file = AsyncMock(return_value=False)
        context = MagicMock()
        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        with patch(
            "music_downloader.telegram.download.run.os.path.getsize",
            return_value=100 * 1024 * 1024,
        ):
            await bot._do_download(context, 1, _make_track(), _make_result(), status_msg, 0, user_id=99999)
        records = bot.history_repo.get_recent(1, chat_id=1)
        assert records[0].status == "failed"
        assert not source.exists()


@patch("music_downloader.telegram.core.app.SpotifyResolver")
@patch("music_downloader.telegram.core.app.SlskdClient")
class TestUserIdThreading:
    @pytest.mark.asyncio
    async def test_single_spotify_match_keeps_user_id(self, mock_slskd, mock_spotify):
        """Single-match auto path must not lose user_id (library ACL depends on it)."""
        bot = MusicBot(_make_config(library_users={12345}))
        bot.spotify.search_multiple = MagicMock(return_value=[_make_track()])
        bot.slskd.search = AsyncMock(return_value=[])
        bot.slskd.parse_results = MagicMock(return_value=[])

        update = MagicMock()
        update.effective_chat.id = 1
        update.effective_user.id = 12345
        searching_msg = MagicMock(message_id=7)
        searching_msg.edit_text = AsyncMock()
        context = MagicMock()
        context.bot.send_message = AsyncMock(return_value=searching_msg)

        await bot._do_search(update, context, "Artist Title", generation=0)
        assert bot.pending[1].user_id == 12345

    @pytest.mark.asyncio
    async def test_duplicate_continue_keeps_user_id(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config(library_users={12345}))
        bot._do_slskd_search = AsyncMock()
        bot.pending[1] = PendingSearch(query="q", track=_make_track(), user_id=None)

        update = MagicMock()
        update.callback_query.from_user.id = 12345
        update.callback_query.edit_message_text = AsyncMock()
        context = MagicMock()
        context.bot.send_message = AsyncMock(return_value=MagicMock(message_id=7))

        await bot._handle_duplicate_response(update, context, 1, "dup:continue")
        assert bot.pending[1].user_id == 12345
        bot._do_slskd_search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_direct_metadata_search_sets_user_id(self, mock_slskd, mock_spotify):
        bot = MusicBot(_make_config(library_users={12345}))
        bot._do_direct_slskd_search = AsyncMock()
        bot._awaiting_direct_metadata[1] = "some query"

        update = MagicMock()
        update.effective_chat.id = 1
        update.effective_user.id = 12345
        update.message.text = "Artist - Title"
        context = MagicMock()
        context.bot.send_message = AsyncMock(return_value=MagicMock(message_id=7))

        await bot.handle_text(update, context)
        assert bot.pending[1].user_id == 12345
        bot._do_direct_slskd_search.assert_awaited_once()
